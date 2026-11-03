"""Retries, Retry-After, quota exhaustion and the generic fallback (scripted loopback servers)."""

import pytest
from testsupport.llm_scenarios import echo_request
from testsupport.loopback_script import ScriptState, Step, serve_script

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import LLMError, PolicyViolation, QuotaExhausted
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm import retry
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RetryPolicy

GITHUB = "github/test/model"
KEY_ENV = "PRUEFSTAND_TEST_KEY"
RATE_LIMITED = {"Retry-After": "2", "x-ratelimit-remaining": "0", "x-ratelimit-limit": "15"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "synthetic-test-value")


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def fake_pause(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(retry, "pause", fake_pause)
    return slept


def _req(model: str = GITHUB) -> LLMRequest:
    return echo_request().model_copy(update={"model": model})


def _client(
    base: str,
    *,
    model: str = GITHUB,
    fallback: LiteLLMBackend | None = None,
    policy: LLMPolicyConfig | None = None,
    timeout_s: float = 30,
    max_retries: int = 2,
) -> tuple[LLMClient, CallRecorder]:
    backend = LiteLLMBackend(model, api_base=f"{base}/v1", api_key_env=KEY_ENV, timeout_s=timeout_s)
    recorder = CallRecorder()
    client = LLMClient(
        backend,
        None,
        Budget(max_usd=None, max_tokens=None),
        recorder,
        LLMPolicy(policy or LLMPolicyConfig()),
        fallback=fallback,
        retry=RetryPolicy(max_retries=max_retries, base_s=0.5, cap_s=8.0, jitter=0.0),
    )
    return client, recorder


def _posts(state: ScriptState) -> int:
    return state.posts()


async def test_two_429_then_ok_makes_three_calls_and_records_every_attempt(
    delays: list[float],
) -> None:
    steps = [Step(429, {"Retry-After": "1"}), Step(429, {"Retry-After": "1"})]
    with serve_script(steps) as (base, state):
        client, recorder = _client(base)
        resp = await client.complete(_req())
    assert resp.text == "OK"
    assert _posts(state) == 3
    assert len(delays) == 2
    errors = [row["error"] for row in recorder.rows]
    assert [e is not None for e in errors] == [True, True, False]


async def test_retry_after_is_respected(delays: list[float]) -> None:
    with serve_script([Step(429, RATE_LIMITED)]) as (base, _):
        client, _rec = _client(base)
        await client.complete(_req())
    assert delays
    assert delays[0] >= 2.0


async def test_a_400_is_not_retried(delays: list[float]) -> None:
    with serve_script([Step(400)]) as (base, state):
        client, recorder = _client(base)
        with pytest.raises(LLMError) as info:
            await client.complete(_req())
    assert info.value.transient is False
    assert _posts(state) == 1
    assert delays == []
    assert len(recorder.rows) == 1
    assert recorder.rows[0]["error"]


async def test_5xx_is_retried(delays: list[float]) -> None:
    with serve_script([Step(503)]) as (base, state):
        client, _ = _client(base, model="openai_compatible_local/m")
        resp = await client.complete(_req("openai_compatible_local/m"))
    assert resp.text == "OK"
    assert _posts(state) == 2
    assert len(delays) == 1


async def test_a_timeout_is_transient_after_the_retries(delays: list[float]) -> None:
    steps = [Step(delay_s=3), Step(delay_s=3)]
    with serve_script(steps) as (base, state):
        client, recorder = _client(
            base, model="openai_compatible_local/m", timeout_s=1, max_retries=1
        )
        with pytest.raises(LLMError) as info:
            await client.complete(_req("openai_compatible_local/m"))
    assert info.value.transient is True
    assert _posts(state) == 2
    assert all(row["error"] for row in recorder.rows)
    assert len(delays) == 1


async def test_exhausted_github_quota_raises_and_later_calls_make_no_network_call(
    delays: list[float],
) -> None:
    with serve_script([Step(429, {"Retry-After": "1"})] * 3) as (base, state):
        client, recorder = _client(base)
        with pytest.raises(QuotaExhausted):
            await client.complete(_req())
        seen = _posts(state)
        assert seen == 3
        with pytest.raises(QuotaExhausted):
            await client.complete(_req())
        assert _posts(state) == seen
    assert recorder.rows[-1]["error"]
    assert len(delays) == 2


async def test_a_retry_after_beyond_the_wait_cap_is_a_daily_limit(delays: list[float]) -> None:
    with serve_script([Step(429, {"Retry-After": "3600"})]) as (base, state):
        client, _ = _client(base)
        with pytest.raises(QuotaExhausted):
            await client.complete(_req())
    assert _posts(state) == 1
    assert delays == []


async def test_a_local_provider_429_stays_a_plain_transient_error(delays: list[float]) -> None:
    model = "openai_compatible_local/m"
    with serve_script([Step(429)] * 3) as (base, _):
        client, _ = _client(base, model=model)
        with pytest.raises(LLMError) as info:
            await client.complete(_req(model))
    assert not isinstance(info.value, QuotaExhausted)
    assert info.value.transient is True


async def test_fallback_serves_after_exhaustion_and_later_calls_skip_the_primary(
    delays: list[float],
) -> None:
    model = "openai_compatible_local/fb"
    with (
        serve_script([Step(429, {"Retry-After": "1"})] * 3) as (primary, pstate),
        serve_script(content="FB") as (second, sstate),
    ):
        fallback = LiteLLMBackend(model, api_base=f"{second}/v1", api_key_env=None, timeout_s=30)
        client, recorder = _client(primary, fallback=fallback)
        first = await client.complete(_req())
        after = _posts(pstate)
        again = await client.complete(_req())
        assert _posts(pstate) == after
        assert _posts(sstate) == 2
    assert first.fallback is True
    assert again.fallback is True
    assert first.text == "FB"
    assert [row["fallback"] for row in recorder.rows][-2:] == [True, True]


async def test_the_fallback_provider_goes_through_the_policy(delays: list[float]) -> None:
    model = "openai_compatible_local/fb"
    only_github = LLMPolicyConfig(allowed_providers=("github",))
    with (
        serve_script([Step(429, {"Retry-After": "1"})] * 3) as (primary, _),
        serve_script() as (second, sstate),
    ):
        fallback = LiteLLMBackend(model, api_base=f"{second}/v1", api_key_env=None, timeout_s=30)
        client, _ = _client(primary, fallback=fallback, policy=only_github)
        with pytest.raises(PolicyViolation):
            await client.complete(_req())
        assert _posts(sstate) == 0
