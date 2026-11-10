"""Sign (c) of the cut check and the exact judge-token count (T5.2c, D1010)."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from testsupport.gpu_files import OPTIONS, SHIPPED_CATALOGUE, write_endpoints
from testsupport.judge_support import DE_ROOT, MODEL, NONCE_KEY, TAGS
from testsupport.loopback_script import Step, serve_script
from tokenizers import Regex, Tokenizer, models, pre_tokenizers

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, JudgeInputTruncated
from pruefstand.judges.exact_tokens import (
    TEMPLATE_TOKENS,
    ExactCounter,
    is_cut,
    load_counter,
    source_url,
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


# --- the counter ----------------------------------------------------------------------------


def test_the_pin_of_the_shipped_judge_is_a_commit_and_the_url_follows_it() -> None:
    entry = yaml.safe_load(SHIPPED_CATALOGUE.read_text(encoding="utf-8"))["models"]
    pin = next(e for e in entry if e["id"] == "ollama/gemma3:12b")["tokenizer"]
    assert "@9478e665381f42974aa06177b019352fb6291876/" in pin["source"]
    assert source_url(pin["source"]).startswith("https://huggingface.co/unsloth/gemma-3-12b-it/")
    assert len(pin["sha256"]) == 64


def test_without_the_file_there_is_no_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=False)
    assert load_counter(MODEL) is None
    assert load_counter("github/openai/gpt-4.1-mini") is None


def test_a_file_that_does_not_match_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = install_tokenizer(tmp_path, monkeypatch, present=True)
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ConfigError, match="differs from the catalogue pin"):
        load_counter(MODEL)


def test_the_counter_counts_exactly_and_adds_the_calibrated_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    counter = load_counter(MODEL)
    assert isinstance(counter, ExactCounter)
    assert counter.count("abc") == 3
    assert TEMPLATE_TOKENS == 10  # 910 - 1.8 x 500 = ... = 10810 - 1.8 x 6000 (D1010)


def test_the_sign_is_a_function_of_window_report_and_cacheable_prefix() -> None:
    assert is_cut(6_147, 14_000, 1_500, 11_904)  # the measured cut
    assert not is_cut(300, 3_000, 1_500, 11_904)  # a short prompt served from cache
    assert not is_cut(11_000, 11_500, 1_500, 11_904)  # honest
    assert not is_cut(
        10_000, 11_500, 1_500, 11_904
    )  # honest, a part of it cached (>= 0.8 x 10 000)
    assert is_cut(7_900, 11_500, 1_500, 11_904)  # well below even a cached report


# --- the four branches of Judge._check_not_cut -------------------------------------------------


async def test_a_report_at_the_window_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        judge_on(tmp_path, monkeypatch, WINDOW) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="window leaves"),
    ):
        await judge.score(long_task(40))


async def test_the_measured_signature_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        judge_on(tmp_path, monkeypatch, NUM_CTX // 2 + 3) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="signature of a cut prompt"),
    ):
        await judge.score(long_task(40))


async def test_a_report_far_below_the_exact_count_of_a_prompt_that_fills_the_window_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = _probe(tmp_path, monkeypatch)
    chars = 0
    task = long_task(40)
    while True:  # grow the answer until the exact count fills 0.95 of the window
        chars += 100
        task = long_task(chars)
        exact, prefix = exact_of(probe, task)
        if exact >= 0.95 * WINDOW:
            break
    assert probe.prompt_tokens(task) <= probe.input_cap  # the estimate lets it through
    reported = int(0.7 * (exact - prefix))
    assert reported < WINDOW
    assert not NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16
    with (
        judge_on(tmp_path, monkeypatch, reported) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="the input was cut"),
    ):
        await judge.score(task)


def _probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Judge, int]:
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=policy)
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    return Judge(client, MODEL, PromptRegistry([DE_ROOT]), nonce_key=NONCE_KEY), 0


async def test_an_honest_report_and_a_cached_short_prompt_are_not_cuts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = _probe(tmp_path, monkeypatch)
    task = long_task(300)
    exact, prefix = exact_of(probe, task)
    assert exact < 0.9 * WINDOW
    for reported in (exact, exact - prefix, 7):  # honest, full prefix cache hit, tiny repeat
        if NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16:
            continue
        with judge_on(tmp_path / f"r{reported}", monkeypatch, reported) as (judge, _):
            assert (await judge.score(task)).raw_score == 1


async def test_without_the_tokenizer_sign_c_is_skipped_and_the_run_can_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_dir = tmp_path / "with"
    probe_dir.mkdir()
    install_tokenizer(probe_dir, monkeypatch, present=True)
    probe, _ = _probe(probe_dir, monkeypatch)
    task = long_task(2_600)
    exact, prefix = exact_of(probe, task)
    assert exact >= 0.9 * WINDOW
    reported = int(0.7 * (exact - prefix))
    absent = tmp_path / "without"
    absent.mkdir()
    with judge_on(absent, monkeypatch, reported, present=False) as (judge, _):
        assert judge.exact_available is False
        assert (await judge.score(task)).raw_score == 1  # (a) and (b) do not hold, (c) is skipped
