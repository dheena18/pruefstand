"""LLMClient against cassettes recorded from the real llama.cpp test model (no network)."""

import pytest
from pydantic import BaseModel

from pruefstand.core.errors import BudgetExceeded, LLMError
from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient, cache_key
from pruefstand.llm.json_extract import extract_json_object
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from testsupport.llm_scenarios import (
    TEST_API_BASE,
    TEST_MODEL,
    DictCache,
    echo_request,
    json_probe_request,
)


class Probe(BaseModel):
    reason: str
    score: int


def _client(
    cache: DictCache | None = None, budget: Budget | None = None
) -> tuple[LLMClient, CallRecorder, Budget]:
    backend = LiteLLMBackend(TEST_MODEL, api_base=TEST_API_BASE, api_key_env=None, timeout_s=30)
    recorder = CallRecorder()
    used = budget or Budget(max_usd=None, max_tokens=None, max_requests=5)
    client = LLMClient(backend, cache, used, recorder, LLMPolicy(LLMPolicyConfig()))
    return client, recorder, used


@pytest.mark.vcr("echo_ok.yaml")
async def test_echo_ok_is_recorded() -> None:
    client, recorder, _ = _client()
    resp = await client.complete(echo_request())
    assert resp.text.strip()
    assert resp.usage.prompt_tokens > 0
    assert resp.cached is False
    assert len(recorder.rows) == 1
    assert recorder.rows[0]["prompt_id"] == "echo"
    assert recorder.rows[0]["prompt_version"] == "v1"
    assert recorder.rows[0]["error"] is None


@pytest.mark.vcr("echo_ok.yaml")
async def test_second_identical_request_hits_the_cache() -> None:
    cache = DictCache()
    client, recorder, budget = _client(cache)
    first = await client.complete(echo_request())
    second = await client.complete(echo_request())  # a second HTTP exchange would fail the vcr
    assert second.cached is True
    assert second.text == first.text
    assert second.usage == first.usage
    assert budget.requests_remaining == 4  # charged once
    assert len(cache.data) == 1
    assert len(recorder.rows) == 2
    assert recorder.rows[1]["cached"] is True


def test_cache_key_covers_every_request_field() -> None:
    base = echo_request()
    assert cache_key(base) == cache_key(echo_request())
    assert cache_key(base) != cache_key(echo_request(temperature=0.7))
    assert cache_key(base) != cache_key(echo_request(max_tokens=32))
    assert cache_key(base) != cache_key(echo_request(seed=1))
    assert cache_key(base) != cache_key(echo_request(word="Meier"))
    assert cache_key(base) != cache_key(base.model_copy(update={"response_format": "json"}))
    assert cache_key(base) != cache_key(base.model_copy(update={"prompt_version": "v2"}))
    assert cache_key(base) != cache_key(base.model_copy(update={"model": "github/x"}))


@pytest.mark.vcr("echo_ok.yaml")
async def test_budget_exceeded_propagates_and_is_not_swallowed() -> None:
    client, recorder, _ = _client(budget=Budget(max_usd=None, max_tokens=1))
    with pytest.raises(BudgetExceeded):
        await client.complete(echo_request())
    assert len(recorder.rows) == 1  # the real call happened and is recorded


@pytest.mark.vcr("json_fenced.yaml")
async def test_fenced_json_from_a_real_model_is_extracted() -> None:
    client, _, _ = _client()
    resp = await client.complete(json_probe_request(max_tokens=128, response_format="text"))
    assert "```" in resp.text
    raw = extract_json_object(resp.text)
    assert raw is not None
    parsed = Probe.model_validate_json(raw)
    assert parsed.reason


@pytest.mark.vcr("json_invalid_then_valid.yaml")
async def test_truncated_json_is_repaired_with_doubled_max_tokens() -> None:
    client, recorder, _ = _client()
    parsed = await client.complete_json(json_probe_request(max_tokens=12), Probe)
    assert parsed.reason
    assert len(recorder.rows) == 2


@pytest.mark.vcr("server_503.yaml")
async def test_server_503_is_a_transient_llm_error() -> None:
    client, recorder, _ = _client()
    with pytest.raises(LLMError) as info:
        await client.complete(echo_request())
    assert info.value.transient is True
    assert info.value.status == 503
    assert len(recorder.rows) == 1
    assert recorder.rows[0]["error"]
    assert recorder.rows[0]["prompt_tokens"] == 0


async def test_policy_violation_makes_no_call_and_is_recorded() -> None:
    client, recorder, _ = _client()
    req: LLMRequest = echo_request().model_copy(update={"model": "openai/gpt-4o"})
    with pytest.raises(LLMError, match="not in allowed_providers"):
        await client.complete(req)
    assert recorder.rows[0]["error"]
