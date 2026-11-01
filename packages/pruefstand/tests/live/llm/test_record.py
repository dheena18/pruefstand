"""Recording scenarios for `make cassettes` (`--record-mode=rewrite`): REAL exchanges only.

Skipped in ordinary live runs; `scripts/models/record_cassettes.sh` runs them against the pinned
llama.cpp test model, then verifies each cassette shows the intended behaviour.
"""

import asyncio
import os
import shlex
import socket
import subprocess
import time
from urllib.parse import urlparse

import pytest
from pydantic import BaseModel
from testsupport.llm_scenarios import (
    BACKEND_CASSETTE_DIR,
    TEST_MODEL,
    echo_request,
    json_probe_request,
)

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import LLMError
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

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
        backend,
        None,
        Budget(max_usd=None, max_tokens=None),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig()),
    )
    return client, backend


@pytest.mark.default_cassette("echo_ok.yaml")
@pytest.mark.vcr
async def test_record_echo_ok() -> None:
    client, _ = _client()
    resp = await client.complete(echo_request())
    assert resp.text.strip()


@pytest.mark.default_cassette("json_fenced.yaml")
@pytest.mark.vcr
async def test_record_json_fenced() -> None:
    client, _ = _client()
    resp = await client.complete(json_probe_request(max_tokens=128, response_format="text"))
    assert "```" in resp.text, (
        "the model did not fence its JSON; the cassette would not show the behaviour"
    )


@pytest.mark.default_cassette("json_invalid_then_valid.yaml")
@pytest.mark.vcr
async def test_record_json_invalid_then_valid() -> None:
    _, backend = _client()
    recorder = CallRecorder()
    client = LLMClient(
        backend, None, Budget(max_usd=None, max_tokens=None), recorder, LLMPolicy(LLMPolicyConfig())
    )
    parsed = await client.complete_json(json_probe_request(max_tokens=12), Probe)
    assert parsed.reason
    assert len(recorder.rows) == 2, "the first answer was not truncated; widen or narrow max_tokens"


def _health_status(host: str, port: int) -> int | None:
    """Raw-socket ``GET /health`` (not an http library, so the vcr patches stay out of it)."""
    try:
        with socket.create_connection((host, port), timeout=0.5) as sock:
            sock.sendall(b"GET /health HTTP/1.0\r\nHost: probe\r\n\r\n")
            line = sock.recv(64).split(b"\r\n", 1)[0].split()
    except OSError:
        return None
    return int(line[1]) if len(line) > 1 and line[1].isdigit() else None


@pytest.mark.default_cassette("server_503.yaml")
@pytest.mark.vcr
async def test_record_server_503_while_loading() -> None:
    """Start the server (``PRUEFSTAND_RECORD_START_CMD``) and call it while it loads the model."""
    start_cmd = os.environ.get("PRUEFSTAND_RECORD_START_CMD")
    if not start_cmd:
        pytest.skip("PRUEFSTAND_RECORD_START_CMD not set (record_cassettes.sh sets it)")
    parsed = urlparse(_base())
    host, port = parsed.hostname or "localhost", parsed.port or 80
    client, _ = _client()
    with pytest.raises(
        LLMError
    ):  # warm-up against the closed port: client set-up must not eat the 503 window
        await client.complete(echo_request())
    starter = subprocess.Popen(  # noqa: ASYNC220, S603  (command of the recording script)
        shlex.split(start_cmd)
    )
    try:
        deadline = time.monotonic() + 60
        while _health_status(host, port) != 503:
            assert time.monotonic() < deadline, "no 503 seen"
            await asyncio.sleep(0.01)
        with pytest.raises(LLMError) as info:
            await client.complete(echo_request())
        assert info.value.status == 503, "the model finished loading first; the script retries"
    finally:
        starter.wait(timeout=120)


async def test_record_backend_cassettes() -> None:
    _, backend = _client()
    recording = CassetteRecorder(BACKEND_CASSETTE_DIR, "record").wrap(backend)
    await recording.acomplete(echo_request())
    await recording.acomplete(json_probe_request(max_tokens=128))
