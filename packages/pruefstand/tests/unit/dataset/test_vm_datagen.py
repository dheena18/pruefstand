"""The VM datagen backend (D1201): served-alias check, loopback-only URL, no hidden resends."""

import socket

import pytest
from testsupport.vm_stub import openai_stub

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.dataset.datagen_guard import build_datagen_client
from pruefstand.dataset.datagen_pins import VM_DATAGEN_MODEL
from pruefstand.dataset.vm_datagen import VM_TIMEOUT_S, build_vm_backend, check_vm_served
from pruefstand.llm.recorder import CallRecorder

ALIAS = "ministral-3-14b-instruct-2512"
TIER1 = "qwen2.5-0.5b-instruct"  # what the tier-1 llama.cpp serves on the judge URL
REF = ModelRef(id=VM_DATAGEN_MODEL, family="mistral")


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_a_server_that_serves_another_model_is_refused() -> None:
    with (
        openai_stub([TIER1]) as (url, _),
        pytest.raises(ConfigError, match=rf"serves \['{TIER1}'\], not {ALIAS}"),
    ):
        check_vm_served(VM_DATAGEN_MODEL, url)


def test_the_pinned_alias_passes() -> None:
    with openai_stub([ALIAS]) as (url, _):
        check_vm_served(VM_DATAGEN_MODEL, url)


def test_nothing_listening_is_refused_with_the_start_command() -> None:
    with pytest.raises(ConfigError, match=r"does not answer.*vm_llm\.sh start"):
        check_vm_served(VM_DATAGEN_MODEL, f"http://127.0.0.1:{_closed_port()}/v1", timeout_s=2.0)


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:18091/v1", "https://127.0.0.1:18091/v1", "http://example.org/v1"]
)
def test_only_plain_http_on_loopback_is_accepted(url: str) -> None:
    with pytest.raises(ConfigError, match="loopback"):
        check_vm_served(VM_DATAGEN_MODEL, url)


def test_the_backend_has_the_long_timeout_and_the_datagen_url() -> None:
    with openai_stub([ALIAS]) as (url, _):
        backend = build_vm_backend(REF, url + "/")
    assert backend.timeout_s == VM_TIMEOUT_S >= 600
    assert backend.api_base == url


def test_the_datagen_client_ignores_the_judge_url(monkeypatch: pytest.MonkeyPatch) -> None:
    with openai_stub([ALIAS]) as (judge_url, _):
        monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", judge_url)  # serves the right alias...
        monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", f"http://127.0.0.1:{_closed_port()}/v1")
        with pytest.raises(ConfigError, match="does not answer"):  # ...but is never asked
            build_datagen_client(
                REF,
                cache=None,
                max_requests=1,
                recorder=CallRecorder(),
                canaries=CanaryRegistry(canaries=()),
            )


def test_the_vm_client_makes_no_transport_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    with openai_stub([ALIAS]) as (url, _):
        monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", url)
        client = build_datagen_client(
            REF,
            cache=None,
            max_requests=1,
            recorder=CallRecorder(),
            canaries=CanaryRegistry(canaries=()),
        )
    assert client._retrier._policy.max_retries == 0  # reason: the policy is the point
