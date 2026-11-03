"""Cache integrity: effective options, unknown versions, invalid answers, caps, fallback."""

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel
from testsupport.gpu_files import OPTIONS
from testsupport.llm_scenarios import DictCache, echo_request
from testsupport.loopback import completion_json
from testsupport.loopback_script import Step, serve_script

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import LLMError, QuotaExhausted
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm import retry
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RetryPolicy

MODEL = "ollama/judge-x:1b"
LOCAL = "openai_compatible_local/m"
TAGS = {"models": [{"name": "judge-x:1b", "digest": "sha256:" + "a" * 64}]}


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str, **options: int) -> None:
    entry = {
        "id": MODEL,
        "engine": "ollama",
        "tag": "judge-x:1b",
        "options": {**OPTIONS, **options},
    }
    catalogue = tmp_path / "models.yaml"
    catalogue.write_text(yaml.safe_dump({"models": [entry]}), encoding="utf-8")
    endpoints = tmp_path / "ep.yaml"
    endpoints.write_text(
        yaml.safe_dump(
            {"endpoints": {"j": {"base_url_env": "T_URL", "model_id": MODEL, "kind": "chat"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
    monkeypatch.setenv("T_URL", origin)


def _req(model: str) -> LLMRequest:
    return echo_request().model_copy(update={"model": model})


def _client(backend: LiteLLMBackend, cache: DictCache, **kw: object) -> LLMClient:
    return LLMClient(
        backend,
        cache,
        Budget(None, None),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig()),
        **kw,  # type: ignore[arg-type]
    )


async def test_a_changed_catalogue_option_misses_although_the_digest_is_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = DictCache()
    with serve_script(tags=TAGS) as (origin, state):
        for num_predict, posts in ((384, 1), (384, 1), (512, 2)):
            _setup(tmp_path, monkeypatch, origin, num_predict=num_predict)
            backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=LLMPolicyConfig())
            assert isinstance(backend, LiteLLMBackend)
            await _client(backend, cache).complete(_req(MODEL))
            chats = sum(1 for s in state.seen if s.path == "/api/chat")
            assert chats == posts


class FlakyProbe(LiteLLMBackend):
    async def resolve_version(self, model: str) -> str | None:
        msg = "probe down"
        raise LLMError(msg, transient=True)


async def test_an_unknown_version_neither_reads_nor_writes_the_cache() -> None:
    cache = DictCache()
    with serve_script() as (origin, state):
        backend = FlakyProbe(LOCAL, api_base=f"{origin}/v1", api_key_env=None, timeout_s=30)
        client = _client(backend, cache)
        await client.complete(_req(LOCAL))
        await client.complete(_req(LOCAL))
        assert state.posts() == 2
    assert not cache.data


class Verdict(BaseModel):
    reason: str
    score: int


async def test_invalid_json_and_empty_answers_are_not_cached() -> None:
    cache = DictCache()
    good = completion_json('{"reason": "ok", "score": 1}')
    steps = [
        Step(body=completion_json("kein JSON")),
        Step(body=good),
        Step(body=completion_json("")),
    ]
    with serve_script(steps, tags={"model_path": "a.gguf"}) as (origin, _):
        backend = LiteLLMBackend(LOCAL, api_base=f"{origin}/v1", api_key_env=None, timeout_s=30)
        client = _client(backend, cache)
        result = await client.complete_json(_req(LOCAL), Verdict)
        assert result.score == 1
        assert len(cache.data) == 1  # only the validated repair answer
        await client.complete(_req(LOCAL).model_copy(update={"prompt_version": "v9"}))
    assert len(cache.data) == 1  # the empty answer was not stored


async def test_a_local_retry_after_above_the_cap_does_not_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def fake_pause(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(retry, "pause", fake_pause)
    with serve_script([Step(429, {"Retry-After": "3600"})]) as (origin, state):
        backend = LiteLLMBackend(LOCAL, api_base=f"{origin}/v1", api_key_env=None, timeout_s=30)
        client = _client(backend, DictCache(), retry=RetryPolicy(max_retries=3))
        with pytest.raises(LLMError) as info:
            await client.complete(_req(LOCAL))
        assert state.posts() == 1
    assert not isinstance(info.value, QuotaExhausted)
    assert slept == []


async def test_an_exhausted_fallback_is_marked_and_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_pause(seconds: float) -> None:
        return None

    monkeypatch.setattr(retry, "pause", fake_pause)
    monkeypatch.setenv("T51_KEY", "synthetic-test-value")
    limited = [Step(429, {"Retry-After": "1"})] * 8
    with serve_script(limited) as (a, sa), serve_script(limited) as (b, sb):
        primary = LiteLLMBackend(
            "github/t/p", api_base=f"{a}/v1", api_key_env="T51_KEY", timeout_s=30
        )
        fallback = LiteLLMBackend(
            "github/t/f", api_base=f"{b}/v1", api_key_env="T51_KEY", timeout_s=30
        )
        client = _client(
            primary, DictCache(), fallback=fallback, retry=RetryPolicy(max_retries=1, jitter=0.0)
        )
        for _ in range(2):
            with pytest.raises(QuotaExhausted):
                await client.complete(_req("github/t/p"))
        assert sa.posts() == 2  # the primary was tried once, then marked exhausted
        assert sb.posts() == 2  # the fallback likewise: no network call on the second request
