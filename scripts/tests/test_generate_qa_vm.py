"""generate_qa on the VM datagen backend (D1201): default pin and the served-model check."""

import socket

import pytest
from generate_qa_args import build_parser
from generate_qa_clients import check_vm_served, default_client

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


def test_no_url_is_refused_with_the_start_command() -> None:
    with pytest.raises(ConfigError, match=r"vm_llm\.sh start"):
        check_vm_served(VM_DATAGEN_MODEL, None)


def test_a_server_that_does_not_answer_is_refused() -> None:
    url = f"http://127.0.0.1:{_closed_port()}/v1"
    with pytest.raises(ConfigError, match="does not answer"):
        check_vm_served(VM_DATAGEN_MODEL, url, timeout_s=2.0)


def test_the_vm_client_needs_no_github_token_but_a_served_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRUEFSTAND_GH_MODELS_TOKEN", raising=False)
    monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", f"http://127.0.0.1:{_closed_port()}/v1")
    ref = ModelRef(id=VM_DATAGEN_MODEL, family="mistral")
    with pytest.raises(ConfigError, match="does not answer"):
        default_client(ref, 1, CallRecorder())
