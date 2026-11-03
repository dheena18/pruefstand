"""The run-time judge-family rule and the judge wiring of ``run_eval`` (T5.2b S3, S5)."""

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import CORPUS_VERSION, case_rows, synthetic_config, write_dataset
from testsupport.run_builders import make_cases
from testsupport.runner_support import SpyPool

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.llm import LLMRequest, LLMResponse, LLMRole, Message
from pruefstand.core.models.target import Usage
from pruefstand.llm.recorder import CallRecorder
from pruefstand.pipeline import run as run_module
from pruefstand.pipeline.run import run_eval


@pytest.fixture(autouse=True)
def tier_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "local")


def serve(router: respx.MockRouter, generator: str | None) -> None:
    """Serve ``/v1/info`` (the generator model, or a 404) and ``/v1/query``."""
    if generator is None:
        router.get("/v1/info").respond(404)
    else:
        info = {
            **load_openapi_example("info.json"),
            "corpus_version": CORPUS_VERSION,
            "models": {"generator": generator},
        }
        router.get("/v1/info").respond(200, json=info)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "ds", {"smoke": case_rows(make_cases(6, split="smoke"))})


def use_pool(monkeypatch: pytest.MonkeyPatch, pool: SpyPool) -> list[dict[str, Any]]:
    given: list[dict[str, Any]] = []

    def build(cfg: object, mode: object, **kwargs: Any) -> SpyPool:
        given.append(kwargs)
        return pool

    monkeypatch.setattr(run_module, "build_judge_pool", build)
    return given


async def go(dataset: Path, tmp_path: Path, **changes: Any) -> Any:
    cfg = synthetic_config(dataset, (Split.SMOKE,), **changes)
    return await run_eval(cfg, tier="pr", out=tmp_path / "runs")


async def test_a_judge_of_the_generator_family_aborts_the_run_before_any_judge_call(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "gpt-4o-mini")  # the configured judge is github/openai/gpt-4.1-mini: family gpt
    pool = SpyPool()
    use_pool(monkeypatch, pool)
    with pytest.raises(ConfigError, match="family") as raised:
        await go(dataset, tmp_path)
    assert pool.tasks == []
    (run_dir,) = (tmp_path / "runs").iterdir()
    stored = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert (stored["complete"], stored["stop_reason"]) == (False, "aborted")
    assert stored["counts"]["judge_family"] == 1
    assert str(run_dir.name) in str(raised.value)


async def test_a_judge_of_another_family_runs(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "qwen3-1.7b-q4_k_m")
    pool = SpyPool()
    use_pool(monkeypatch, pool)
    results = await go(dataset, tmp_path)
    assert results.manifest.complete is True
    assert len(pool.tasks) > 0


async def test_the_fallback_judge_must_come_from_another_family_too(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "qwen3-1.7b-q4_k_m")
    pool = SpyPool()
    use_pool(monkeypatch, pool)
    policy = LLMPolicyConfig(
        allowed_providers=("openai_compatible_local", "ollama", "github"),
        fallback_judge=ModelRef(id="ollama/qwen3:4b", family="qwen"),
    )
    with pytest.raises(ConfigError, match=r"llm\.fallback_judge"):
        await go(dataset, tmp_path, llm=policy)
    assert pool.tasks == []


async def test_an_opaque_target_cannot_be_checked_and_the_run_goes_on(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, None)
    pool = SpyPool()
    use_pool(monkeypatch, pool)
    results = await go(dataset, tmp_path)
    assert results.manifest.complete is True


async def test_the_pool_shares_the_runs_budget_recorder_and_canaries(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "qwen3-1.7b-q4_k_m")
    given = use_pool(monkeypatch, SpyPool())
    await go(dataset, tmp_path)
    (kwargs,) = given
    assert set(kwargs) == {"tier", "budget", "recorder", "canaries", "cache"}
    assert kwargs["tier"] == "pr"


async def test_a_call_answered_by_the_fallback_judge_sets_judge_fallback(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "qwen3-1.7b-q4_k_m")
    recorders: list[CallRecorder] = []

    def build(cfg: object, mode: object, *, recorder: CallRecorder, **kwargs: Any) -> SpyPool:
        recorders.append(recorder)
        request = LLMRequest(
            role=LLMRole.JUDGE,
            model="ollama/x",
            messages=(Message(role="user", content="x"),),
            prompt_id="faithfulness_de",
            prompt_version="v2",
        )
        answer = LLMResponse(
            text="{}",
            model="github/openai/gpt-4.1-mini",
            usage=Usage(prompt_tokens=1, completion_tokens=1),
            cost_usd=0.0, latency_ms=1.0, cached=False, fallback=True,
        )  # fmt: skip
        recorder.record(request, answer, None)
        return SpyPool()

    monkeypatch.setattr(run_module, "build_judge_pool", build)
    results = await go(dataset, tmp_path)
    assert results.manifest.judge_fallback is True
    (run_dir,) = (tmp_path / "runs").iterdir()
    assert (run_dir / "llm_calls.parquet").is_file()


async def test_without_a_fallback_the_flag_stays_off(
    router: respx.MockRouter, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router, "qwen3-1.7b-q4_k_m")
    use_pool(monkeypatch, SpyPool())
    results = await go(dataset, tmp_path)
    assert results.manifest.judge_fallback is False
