"""Judge test setup: a catalogue entry, an endpoints file and a client over a loopback server."""

from pathlib import Path

import pytest
from testsupport.gpu_files import OPTIONS, write_catalogue, write_endpoints

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.protocols import KVCache
from pruefstand.judges.judge import Judge
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

MODEL = "ollama/judge-x:1b"
NONCE_KEY = b"unit-test-nonce-key"  # a fixed test key, as hosted CI uses (docs/ops/secrets.md)
TAGS = {"models": [{"name": "judge-x:1b", "digest": f"sha256:{'c' * 64}"}]}
DE_ROOT = Path(__file__).resolve().parents[2] / "src" / "pruefstand" / "judges" / "prompts"


def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    """Point the Ollama backend at ``origin`` with a one-model catalogue."""
    catalogue = write_catalogue(tmp_path / "models.yaml", {MODEL: OPTIONS})
    endpoints = write_endpoints(tmp_path / "ep.yaml", {"judge": ("T_JUDGE_URL", MODEL)})
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
    monkeypatch.setenv("T_JUDGE_URL", origin)


def make_client(cache: KVCache | None = None) -> tuple[LLMClient, CallRecorder]:
    """Return a client for ``MODEL`` and its call recorder."""
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=policy)
    recorder = CallRecorder()
    return LLMClient(backend, cache, Budget(None, None), recorder, LLMPolicy(policy)), recorder


def make_judge(cache: KVCache | None = None) -> tuple[Judge, CallRecorder]:
    """Return a judge on ``MODEL`` with the shipped prompts and the fixed test nonce key."""
    client, recorder = make_client(cache)
    judge = Judge(client, MODEL, PromptRegistry([DE_ROOT]), nonce_key=NONCE_KEY)
    return judge, recorder
