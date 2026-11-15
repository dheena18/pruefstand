"""generate_qa on the VM datagen backend (D1201): default pin, URL, concurrency, retired GitHub."""

import socket

import pytest
from generate_qa_args import build_parser, effective_concurrency
from generate_qa_clients import default_client

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.dataset.datagen_pins import DATAGEN_MODEL, VM_DATAGEN_MODEL
from pruefstand.llm.recorder import CallRecorder


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _model(monkeypatch: pytest.MonkeyPatch, backend: str | None) -> str:
    if backend is None:
        monkeypatch.delenv("PRUEFSTAND_DATAGEN_BACKEND", raising=False)
    else:
        monkeypatch.setenv("PRUEFSTAND_DATAGEN_BACKEND", backend)
    args = build_parser("x").parse_args(["--tenant", "all", "--n", "1"])
    return str(args.model)


def test_the_default_model_follows_the_backend_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _model(monkeypatch, None) == VM_DATAGEN_MODEL
    assert _model(monkeypatch, "github") == DATAGEN_MODEL


def test_the_vm_model_is_asked_one_request_at_a_time() -> None:
    assert effective_concurrency(4, None, VM_DATAGEN_MODEL) == 1
    assert effective_concurrency(4, None, DATAGEN_MODEL) == 4


def test_the_vm_client_needs_no_github_token_but_a_served_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRUEFSTAND_GH_MODELS_TOKEN", raising=False)
    monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", f"http://127.0.0.1:{_closed_port()}/v1")
    ref = ModelRef(id=VM_DATAGEN_MODEL, family="mistral")
    with pytest.raises(ConfigError, match="does not answer"):
        default_client(ref, 1, CallRecorder())


def test_a_github_model_says_github_models_is_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRUEFSTAND_GH_MODELS_TOKEN", raising=False)
    with pytest.raises(ConfigError, match=r"GitHub Models is retired \(2026-07-30"):
        default_client(ModelRef(id=DATAGEN_MODEL, family="gpt"), 1, CallRecorder())
