"""Real llama.cpp container (tier-1 generator pin, compose profile ``live``): echo and JSON."""

import os

import pytest
from pydantic import BaseModel
from testsupport.llm_scenarios import TEST_MODEL, echo_request, json_probe_request

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

pytestmark = pytest.mark.live


class Verdict(BaseModel):
    reason: str
    score: int


def _client() -> LLMClient:
    base = os.environ.get("PRUEFSTAND_TEST_LLM_URL", "http://localhost:8080/v1")
    backend = LiteLLMBackend(TEST_MODEL, api_base=base, api_key_env=None, timeout_s=120)
    return LLMClient(
        backend, None, Budget(None, None), CallRecorder(), LLMPolicy(LLMPolicyConfig())
    )


async def test_the_container_answers_a_plain_request() -> None:
    resp = await _client().complete(echo_request(max_tokens=32))
    assert resp.text.strip()
    assert resp.cost_usd == 0.0
    assert resp.usage.prompt_tokens > 0


async def test_complete_json_returns_a_valid_object() -> None:
    request = json_probe_request(max_tokens=256)
    result = await _client().complete_json(request, Verdict)
    assert isinstance(result.score, int)
    assert result.reason


async def test_the_second_identical_call_is_not_charged_to_the_cache_free_client() -> None:
    client = _client()
    first = await client.complete(echo_request(max_tokens=16))
    second = await client.complete(echo_request(max_tokens=16))
    assert first.text.strip()
    assert second.text.strip()
