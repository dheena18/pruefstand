"""Hard timeout and bounded responses: hostile loopback servers, real sockets."""

import resource
import time

import pytest
from testsupport.llm_scenarios import echo_request
from testsupport.loopback import serve

from pruefstand.core.errors import LLMError
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.limits import response_limits
from pruefstand.llm.backends.litellm import LiteLLMBackend

MODEL = "openai_compatible_local/loop"


def _req(max_tokens: int = 16) -> LLMRequest:
    return echo_request(max_tokens=max_tokens).model_copy(update={"model": MODEL})


async def test_a_dripping_server_hits_the_hard_timeout() -> None:
    with serve(drip_s=0.5) as base:
        backend = LiteLLMBackend(MODEL, api_base=base, api_key_env=None, timeout_s=2)
        start = time.monotonic()
        with pytest.raises(LLMError) as info:
            await backend.acomplete(_req())
    assert time.monotonic() - start < 6
    assert info.value.transient is True
    assert "timeout" in str(info.value).lower()


async def test_a_huge_body_is_refused_with_bounded_memory() -> None:
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with serve(huge_bytes=60 * 1024 * 1024) as base:
        backend = LiteLLMBackend(MODEL, api_base=base, api_key_env=None, timeout_s=30)
        with pytest.raises(LLMError) as info:
            await backend.acomplete(_req(max_tokens=16))
    grown_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert info.value.transient is False
    assert "too large" in str(info.value)
    assert grown_kib < 80 * 1024


async def test_an_answer_longer_than_max_tokens_allows_is_refused() -> None:
    with serve(content="x" * 20_000) as base:
        backend = LiteLLMBackend(MODEL, api_base=base, api_key_env=None, timeout_s=10)
        with pytest.raises(LLMError, match="too large") as info:
            await backend.acomplete(_req(max_tokens=16))
    assert info.value.transient is False


async def test_a_normal_answer_passes_and_cause_chain_is_clean() -> None:
    with serve(content="Schüler") as base:
        backend = LiteLLMBackend(MODEL, api_base=base, api_key_env=None, timeout_s=10)
        resp = await backend.acomplete(_req())
    assert resp.text == "Schüler"


async def test_errors_do_not_chain_the_provider_exception() -> None:
    backend = LiteLLMBackend(MODEL, api_base="http://127.0.0.1:1/v1", api_key_env=None, timeout_s=5)
    with pytest.raises(LLMError) as info:
        await backend.acomplete(_req())
    assert info.value.__cause__ is None


def test_response_limits_scale_with_max_tokens() -> None:
    small_text, small_bytes = response_limits(16)
    big_text, big_bytes = response_limits(1024)
    assert small_text == 16 * 16 + 4096
    assert big_text > small_text
    assert small_bytes > small_text * 4
    assert big_bytes > big_text * 4
