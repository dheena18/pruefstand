"""The W3.2 cache key (interfaces §8): version, epoch and every rendered input are in it."""

from pathlib import Path

import pytest
from testsupport.llm_scenarios import DictCache, echo_request
from testsupport.loopback_script import ScriptState, serve_script

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest, Message
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cache_epochs import current_epoch, invalidate_judge
from pruefstand.llm.client import LLMClient, cache_key
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

LOCAL = "openai_compatible_local/m"
GITHUB = "github/t/m"


def _req(model: str = LOCAL, **update: object) -> LLMRequest:
    return echo_request().model_copy(update={"model": model, **update})


def _client(
    base: str,
    cache: DictCache,
    *,
    model: str = LOCAL,
    epochs_dir: Path | None = None,
) -> tuple[LLMClient, Budget]:
    backend = LiteLLMBackend(model, api_base=f"{base}/v1", api_key_env=None, timeout_s=30)
    budget = Budget(max_usd=None, max_tokens=None, max_requests=50)
    epochs = None
    if epochs_dir is not None:
        directory = epochs_dir
        epochs = lambda m: current_epoch(directory, m)  # noqa: E731
    client = LLMClient(
        backend, cache, budget, CallRecorder(), LLMPolicy(LLMPolicyConfig()), epochs=epochs
    )
    return client, budget


def _posts(state: ScriptState) -> int:
    return state.posts()


async def test_same_request_twice_calls_the_backend_once() -> None:
    cache = DictCache()
    with serve_script(tags={"model_path": "a.gguf"}) as (base, state):
        client, budget = _client(base, cache)
        first = await client.complete(_req())
        left = budget.requests_remaining
        second = await client.complete(_req())
        assert _posts(state) == 1
    assert first.cached is False
    assert second.cached is True
    assert second.cost_usd == 0.0
    assert budget.requests_remaining == left  # the hit charged no quota


async def test_temperature_above_zero_is_never_cached() -> None:
    cache = DictCache()
    with serve_script(tags={"model_path": "a.gguf"}) as (base, state):
        client, _ = _client(base, cache)
        await client.complete(_req(temperature=0.7))
        await client.complete(_req(temperature=0.7))
        assert _posts(state) == 2
    assert not cache.data


async def test_prompt_version_context_and_reference_are_part_of_the_key() -> None:
    cache = DictCache()
    with serve_script(tags={"model_path": "a.gguf"}) as (base, state):
        client, _ = _client(base, cache)
        await client.complete(_req())
        await client.complete(_req(prompt_version="v2"))
        same_answer = (
            Message(role="user", content="Antwort: A\nKontext: Paragraf 1\nReferenz: R"),
        )
        other_context = (
            Message(role="user", content="Antwort: A\nKontext: Paragraf 2\nReferenz: R"),
        )
        other_reference = (
            Message(role="user", content="Antwort: A\nKontext: Paragraf 1\nReferenz: S"),
        )
        for messages in (same_answer, other_context, other_reference):
            await client.complete(_req(messages=messages))
        assert _posts(state) == 5
        await client.complete(_req(messages=same_answer))
        assert _posts(state) == 5


async def test_another_provider_reported_version_misses() -> None:
    cache = DictCache()
    with serve_script(tags={"model_path": "a.gguf"}) as (base_a, state_a):
        client, _ = _client(base_a, cache)
        await client.complete(_req())
        await client.complete(_req())
        assert _posts(state_a) == 1
    with serve_script(tags={"model_path": "b.gguf"}) as (base_b, state_b):
        client, _ = _client(base_b, cache)
        await client.complete(_req())
        assert _posts(state_b) == 1
    with serve_script(tags={"model_path": "a.gguf"}) as (base_c, state_c):
        client, _ = _client(base_c, cache)
        await client.complete(_req())
        assert _posts(state_c) == 0


async def test_github_version_comes_from_the_first_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_KEY_T", "synthetic-test-value")
    cache = DictCache()
    with serve_script(model_name="gpt-x-2026-01") as (base, state):
        backend = LiteLLMBackend(
            GITHUB, api_base=f"{base}/v1", api_key_env="GITHUB_KEY_T", timeout_s=30
        )
        client = LLMClient(
            backend, cache, Budget(None, None), CallRecorder(), LLMPolicy(LLMPolicyConfig())
        )
        first = await client.complete(_req(GITHUB))
        await client.complete(_req(GITHUB))
        assert _posts(state) == 1  # the second call used the version resolved by the first
    assert first.model_version is not None
    assert first.model_version.endswith("gpt-x-2026-01")


async def test_a_bumped_cache_epoch_misses_for_that_model_only(tmp_path: Path) -> None:
    cache = DictCache()
    with serve_script(tags={"model_path": "a.gguf"}) as (base, state):
        client, _ = _client(base, cache, epochs_dir=tmp_path)
        await client.complete(_req())
        await client.complete(_req())
        assert _posts(state) == 1
        invalidate_judge(tmp_path, "openai_compatible_local/other")
        await client.complete(_req())
        assert _posts(state) == 1
        invalidate_judge(tmp_path, LOCAL)
        await client.complete(_req())
        assert _posts(state) == 2


def test_the_key_equals_the_interfaces_definition() -> None:
    req = _req()
    expected = stable_hash(
        req.model, "ver-1#e3", req.prompt_id, req.prompt_version, req.messages,
        req.temperature, req.max_tokens, req.seed, req.response_format,
    )  # fmt: skip
    assert cache_key(req, "ver-1", 3) == f"llm:{expected}"
    assert cache_key(req, "ver-1", 3) != cache_key(req, "ver-2", 3)
    assert cache_key(req, "ver-1", 3) != cache_key(req, "ver-1", 4)
