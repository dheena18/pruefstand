"""Backend-level CassetteRecorder: replay of recorded real exchanges, and one live record run."""

import json
import os
from pathlib import Path

import pytest

from pruefstand.core.errors import LLMError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.cassettes import CassetteRecorder
from testsupport.llm_scenarios import (
    BACKEND_CASSETTE_DIR,
    TEST_MODEL,
    echo_request,
    json_probe_request,
)


async def test_replay_returns_the_stored_response() -> None:
    backend = CassetteRecorder(BACKEND_CASSETTE_DIR, "replay").wrap(None)
    resp = await backend.acomplete(echo_request())
    assert resp.text.strip()
    assert resp.usage.prompt_tokens > 0
    assert resp.cached is False
    stored = json.loads((BACKEND_CASSETTE_DIR / f"{stable_hash(echo_request())}.json").read_text("utf-8"))
    assert resp.usage.completion_tokens == stored["response"]["usage"]["completion_tokens"]
    assert resp.latency_ms == stored["response"]["latency_ms"]


async def test_replay_of_the_json_probe_cassette() -> None:
    backend = CassetteRecorder(BACKEND_CASSETTE_DIR, "replay").wrap(None)
    resp = await backend.acomplete(json_probe_request(max_tokens=128))
    assert "reason" in resp.text


async def test_cassette_files_hold_no_secret_material_and_are_named_by_hash() -> None:
    files = sorted(BACKEND_CASSETTE_DIR.glob("*.json"))
    assert len(files) >= 2
    for path in files:
        text = path.read_text("utf-8")
        assert "api_key" not in text.lower()
        assert "authorization" not in text.lower()
        assert "bearer" not in text.lower()
        request = LLMRequest.model_validate(json.loads(text)["request"])
        assert path.stem == stable_hash(request)


async def test_replay_miss_raises_and_never_invents_an_answer() -> None:
    backend = CassetteRecorder(BACKEND_CASSETTE_DIR, "replay").wrap(None)
    with pytest.raises(LLMError, match="cassette miss") as info:
        await backend.acomplete(echo_request(seed=12345))
    assert info.value.transient is False
    assert stable_hash(echo_request(seed=12345)) in str(info.value)


def test_record_mode_needs_a_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="backend"):
        CassetteRecorder(tmp_path, "record").wrap(None)


@pytest.mark.live
async def test_record_mode_writes_one_hashed_file_per_request(tmp_path: Path) -> None:
    base = os.environ.get("PRUEFSTAND_TEST_LLM_URL", "http://localhost:8080/v1")
    real = LiteLLMBackend(TEST_MODEL, api_base=base, api_key_env=None, timeout_s=60)
    backend = CassetteRecorder(tmp_path, "record").wrap(real)
    req = echo_request()
    resp = await backend.acomplete(req)
    files = list(tmp_path.glob("*.json"))
    assert [f.name for f in files] == [f"{stable_hash(req)}.json"]
    content = files[0].read_text("utf-8")
    assert "api_key" not in content.lower()
    assert "authorization" not in content.lower()
    data = json.loads(content)
    assert data["response"]["text"] == resp.text
    assert data["model_id"] == TEST_MODEL
    replay = await CassetteRecorder(tmp_path, "replay").wrap(None).acomplete(req)
    assert replay.text == resp.text
