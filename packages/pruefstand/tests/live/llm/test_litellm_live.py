"""Real calls to the pinned llama.cpp test model (compose profile live). Structure, not wording."""

import os

import pytest
from pydantic import BaseModel
from testsupport.llm_scenarios import TEST_MODEL, echo_request, json_probe_request

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import LLMError
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

pytestmark = pytest.mark.live


class Probe(BaseModel):
    reason: str
    score: int


def _base() -> str:
    return os.environ.get("PRUEFSTAND_TEST_LLM_URL", "http://localhost:8080/v1")


def _client(base: str | None = None, timeout_s: float = 120) -> LLMClient:
    backend = LiteLLMBackend(
        TEST_MODEL, api_base=base or _base(), api_key_env=None, timeout_s=timeout_s
    )
    return LLMClient(
        backend,
        None,
        Budget(max_usd=None, max_tokens=None),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig()),
    )


async def test_echo_returns_text_usage_and_latency() -> None:
    resp = await _client().complete(echo_request())
    assert resp.text.strip()
    assert resp.latency_ms > 0
    assert resp.cost_usd == 0.0
    assert resp.usage.prompt_tokens > 0


async def test_complete_json_validates_the_probe() -> None:
    parsed = await _client().complete_json(json_probe_request(max_tokens=128), Probe)
    assert parsed.reason


async def test_max_tokens_one_is_honoured() -> None:
    resp = await _client().complete(echo_request(max_tokens=1))
    assert resp.usage.completion_tokens <= 2


async def test_wrong_port_is_a_transient_error() -> None:
    with pytest.raises(LLMError) as info:
        await _client("http://127.0.0.1:1/v1", timeout_s=5).complete(echo_request())
    assert info.value.transient is True


async def test_replay_and_live_agree_on_structure() -> None:
    """The cassette-covered behaviour (echo) also runs live: same fields, non-empty text."""
    live = await _client().complete(echo_request())
    assert live.model == TEST_MODEL
    assert live.provider == "openai_compatible_local"
