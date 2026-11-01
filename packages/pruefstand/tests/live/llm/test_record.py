"""Recording scenarios for `make cassettes` (`--record-mode=rewrite`): every file is a REAL exchange.

Skipped in ordinary live runs; `scripts/models/record_cassettes.sh` runs them against the pinned
llama.cpp test model, then verifies each cassette shows the intended behaviour.
"""

import os
import socket
import time
from urllib.parse import urlparse

import pytest
from pydantic import BaseModel

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import LLMError
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from testsupport.llm_scenarios import (
    BACKEND_CASSETTE_DIR,
    TEST_MODEL,
    echo_request,
    json_probe_request,
)

pytestmark = pytest.mark.live


class Probe(BaseModel):
    reason: str
    score: int


@pytest.fixture(autouse=True)
def _only_when_recording(request: pytest.FixtureRequest) -> None:
    if request.config.getoption("--record-mode", default=None) != "rewrite":
        pytest.skip("recording scenarios run only with --record-mode=rewrite (make cassettes)")


def _base() -> str:
    return os.environ.get("PRUEFSTAND_TEST_LLM_URL", "http://localhost:8080/v1")


def _client() -> tuple[LLMClient, LiteLLMBackend]:
    backend = LiteLLMBackend(TEST_MODEL, api_base=_base(), api_key_env=None, timeout_s=120)
    client = LLMClient(
        backend, None, Budget(max_usd=None, max_tokens=None), CallRecorder(), LLMPolicy(LLMPolicyConfig())
    )
    return client, backend


@pytest.mark.vcr("echo_ok.yaml")
async def test_record_echo_ok() -> None:
    client, _ = _client()
    resp = await client.complete(echo_request())
    assert resp.text.strip()


@pytest.mark.vcr("json_fenced.yaml")
async def test_record_json_fenced() -> None:
    client, _ = _client()
    resp = await client.complete(json_probe_request(max_tokens=128, response_format="text"))
    assert "```" in resp.text, "the model did not fence its JSON; the cassette would not show the behaviour"


@pytest.mark.vcr("json_invalid_then_valid.yaml")
async def test_record_json_invalid_then_valid() -> None:
    _, backend = _client()
    recorder = CallRecorder()
    client = LLMClient(
        backend, None, Budget(max_usd=None, max_tokens=None), recorder, LLMPolicy(LLMPolicyConfig())
    )
    parsed = await client.complete_json(json_probe_request(max_tokens=12), Probe)
    assert parsed.reason
    assert len(recorder.rows) == 2, "the first answer was not truncated; widen or narrow max_tokens"


@pytest.mark.vcr("server_503.yaml")
async def test_record_server_503_while_loading() -> None:
    """Call the server while it still loads the model (the script restarts it right before)."""
    parsed = urlparse(_base())
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:  # wait for the port, then hit it at once
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((parsed.hostname or "localhost", parsed.port or 80)) == 0:
                break
        time.sleep(0.02)
    client, _ = _client()
    with pytest.raises(LLMError) as info:
        await client.complete(echo_request())
    assert info.value.status == 503, "the model was already loaded; the script retries"


async def test_record_backend_cassettes() -> None:
    _, backend = _client()
    recording = CassetteRecorder(BACKEND_CASSETTE_DIR, "record").wrap(backend)
    await recording.acomplete(echo_request())
    await recording.acomplete(json_probe_request(max_tokens=128))
