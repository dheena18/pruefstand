"""Helpers of the exact judge-token tests: a char-level tokenizer, a pinned catalogue, a judge."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from testsupport.gpu_files import OPTIONS, write_endpoints
from testsupport.judge_support import DE_ROOT, MODEL, NONCE_KEY, TAGS
from testsupport.loopback_script import Step, serve_script
from tokenizers import Regex, Tokenizer, models, pre_tokenizers

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.exact_tokens import (
    load_counter,
    tokenizer_file,
)
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

NUM_CTX = int(OPTIONS["num_ctx"])
WINDOW = NUM_CTX - int(OPTIONS["num_predict"])  # 4096 - 77 = 4019


def char_tokenizer() -> Tokenizer:
    """A real ``tokenizers`` tokenizer that counts one token per character (exact and simple)."""
    vocab = {"[UNK]": 0}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))  # noqa: S106  (a token name)
    tokenizer.pre_tokenizer = pre_tokenizers.Split(Regex("[\\s\\S]"), "isolated")
    return tokenizer


def install_tokenizer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, present: bool) -> Path:
    """A catalogue that pins the char tokenizer; the file is written only when ``present``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    directory = tmp_path / "tok"
    directory.mkdir(exist_ok=True)
    monkeypatch.setenv("T_JUDGE_URL", "http://127.0.0.1:1")
    raw = char_tokenizer().to_str().encode("utf-8")
    pin = {
        "source": "hf:acme/judge-x@abc/tokenizer.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    entry = {
        "id": MODEL,
        "engine": "ollama",
        "tag": MODEL.removeprefix("ollama/"),
        "options": OPTIONS,
        "tokenizer": pin,
    }
    catalogue = tmp_path / "models.yaml"
    catalogue.write_text(yaml.safe_dump({"models": [entry]}), encoding="utf-8")
    endpoints = write_endpoints(tmp_path / "ep.yaml", {"judge": ("T_JUDGE_URL", MODEL)})
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
    monkeypatch.setenv("PRUEFSTAND_JUDGE_TOKENIZER_DIR", str(directory))
    file = tokenizer_file(MODEL)
    if present:
        file.write_bytes(raw)
    return file


@contextmanager
def judge_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reported: int, *, present: bool = True
) -> Iterator[tuple[Judge, list[object]]]:
    install_tokenizer(tmp_path, monkeypatch, present=present)
    body = json.dumps(
        {
            "model": "m",
            "message": {"role": "assistant", "content": '{"reason": "x", "score": 1}'},
            "done": True,
            "prompt_eval_count": reported,
            "eval_count": 2,
        }
    ).encode()
    with serve_script([Step(body=body)], tags=TAGS) as (origin, state):
        monkeypatch.setenv("T_JUDGE_URL", origin)
        policy = LLMPolicyConfig()
        backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=policy)
        client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
        yield Judge(client, MODEL, PromptRegistry([DE_ROOT]), nonce_key=NONCE_KEY), [state]


def long_task(chars: int):  # type: ignore[no-untyped-def]
    """A refusal task whose answer is ``chars`` characters of 12-letter words."""
    answer = ("abcdefghijkl " * (chars // 13 + 1))[:chars]
    return make_task("refusal_judged", frage="F?", antwort=answer)


def exact_of(judge: Judge, task) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    counter = load_counter(MODEL)
    assert counter is not None
    messages = judge._render(task)
    return counter.prompt(messages), counter.fixed_prefix(messages)


def make_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Judge, int]:
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=policy)
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    return Judge(client, MODEL, PromptRegistry([DE_ROOT]), nonce_key=NONCE_KEY), 0


def grow(probe: Judge, fraction: float):  # type: ignore[no-untyped-def]
    """The shortest answer whose exact prompt count is at least ``fraction`` of the window."""
    chars = 0
    while True:
        chars += 50
        task = long_task(chars)
        exact, prefix = exact_of(probe, task)
        if exact >= fraction * WINDOW:
            return task, exact, prefix
