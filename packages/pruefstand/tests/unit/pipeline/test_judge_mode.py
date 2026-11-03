"""Judge mode resolution and its record in ``run.json`` (T1.10 S4, round-8 W1.4 / W3.9)."""

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import case_rows, synthetic_config, write_dataset
from testsupport.run_builders import make_cases
from testsupport.runner_support import SpyPool, StubJudgedMetric

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, LLMError, QuotaExhausted
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.models.run import RunResults
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline import run as run_module
from pruefstand.pipeline.judge_mode import (
    fallback_used,
    final_judge_mode,
    requested_judge_mode,
    resolve_stack,
)
from pruefstand.pipeline.run import run_eval
from pruefstand.runner.runner import Runner

TOKEN_ENV = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  (a variable name, not a secret)
SYNTHETIC_TOKEN = "synthetic-test-value"  # noqa: S105


def test_follows_the_stack_when_nothing_is_forced() -> None:
    assert requested_judge_mode(stack="live", env={}, has_models_token=True) == "github"
    assert requested_judge_mode(stack="a40", env={}, has_models_token=False) == "local"


def test_tier_one_without_a_models_token_is_skipped() -> None:
    assert requested_judge_mode(stack="live", env={}, has_models_token=False) == "skipped"


def test_skipped_in_the_environment_wins() -> None:
    env = {"PRUEFSTAND_JUDGE_MODE": "skipped"}
    assert requested_judge_mode(stack="a40", env=env, has_models_token=True) == "skipped"


def test_cpu_is_not_a_judge_mode() -> None:
    with pytest.raises(ConfigError, match="cpu"):
        requested_judge_mode(
            stack="live", env={"PRUEFSTAND_JUDGE_MODE": "cpu"}, has_models_token=True
        )


def test_an_odd_value_is_never_echoed() -> None:
    odd = "sk-" + "a1" * 12
    with pytest.raises(ConfigError) as mode:
        requested_judge_mode(
            stack="live", env={"PRUEFSTAND_JUDGE_MODE": odd}, has_models_token=True
        )
    with pytest.raises(ConfigError) as stack:
        resolve_stack({"PRUEFSTAND_STACK": odd})
    assert odd not in str(mode.value)
    assert odd not in str(stack.value)


def test_a_judge_mode_that_never_judged_is_skipped() -> None:
    assert final_judge_mode("github", judged_cases=0) == "skipped"
    assert final_judge_mode("github", judged_cases=3) == "github"
    assert final_judge_mode("skipped", judged_cases=3) == "skipped"


@pytest.fixture
def dataset(tmp_path: Path, router: respx.MockRouter) -> Path:
    router.get("/v1/info").respond(404)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    rows = case_rows(make_cases(20, split="smoke"))
    return write_dataset(tmp_path / "ds", {"smoke": rows})


def use_stub_judges(monkeypatch: pytest.MonkeyPatch, pool: SpyPool) -> None:
    registry = MetricRegistry([*MetricRegistry.default().all(), StubJudgedMetric()])
    monkeypatch.setattr(run_module, "build_registry", lambda: registry)
    monkeypatch.setattr(run_module, "build_judge_pool", lambda cfg, mode: pool)


async def go(dataset: Path, tmp_path: Path) -> RunResults:
    return await run_eval(
        synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "runs"
    )


async def test_skipped_forces_the_runner_to_get_no_judges(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = SpyPool()
    use_stub_judges(monkeypatch, pool)
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "skipped")
    given: list[Any] = []
    original = Runner.__init__

    def spy(
        self: Runner, adapter: Any, metrics: Any, judges: Any, *args: Any, **kwargs: Any
    ) -> None:
        given.append(judges)
        original(self, adapter, metrics, judges, *args, **kwargs)

    monkeypatch.setattr(Runner, "__init__", spy)
    results = await go(dataset, tmp_path)
    assert given == [None]
    assert results.manifest.judge_mode == "skipped"
    assert pool.score_calls == []


async def test_live_stack_with_judged_values_is_github(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_stub_judges(monkeypatch, SpyPool())
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)
    results = await go(dataset, tmp_path)
    assert (results.manifest.stack, results.manifest.judge_mode) == ("live", "github")
    assert results.manifest.judged_cases == 20


async def test_a40_stack_is_local(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_stub_judges(monkeypatch, SpyPool())
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    results = await go(dataset, tmp_path)
    assert (results.manifest.stack, results.manifest.judge_mode) == ("a40", "local")


async def test_no_judged_value_downgrades_to_skipped(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")  # the default registry has no judged metric yet
    results = await go(dataset, tmp_path)
    assert results.manifest.judge_mode == "skipped"
    assert results.manifest.judged_cases == 0
    assert results.manifest.judge_fallback is False


async def test_judge_degraded_and_judged_cases_reach_run_json(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def act(task: JudgeTask) -> None:
        if task.inputs["case_id"] in {"law-0003", "law-0004"}:
            message = "judge down"
            raise LLMError(message, transient=True)

    use_stub_judges(monkeypatch, SpyPool(act))
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    results = await go(dataset, tmp_path)
    stored = json.loads(
        (next((tmp_path / "runs").iterdir()) / "run.json").read_text(encoding="utf-8")
    )
    assert stored["judge_degraded"] is True
    assert stored["judged_cases"] == 20
    assert results.manifest.judge_degraded is True
    assert results.manifest.judged_cases == 20


async def test_an_unknown_stack_is_a_config_error(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_STACK", "gpu")
    with pytest.raises(ConfigError, match="PRUEFSTAND_STACK"):
        await go(dataset, tmp_path)


async def test_cpu_judge_mode_in_run_eval_is_a_config_error(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "cpu")
    with pytest.raises(ConfigError, match="cpu"):
        await go(dataset, tmp_path)


# --- T5.1: quota skips, fallback rows, drift flag ----------------------------------------------


def test_quota_skipped_values_downgrade_the_mode_to_skipped() -> None:
    assert final_judge_mode("github", judged_cases=3, quota_skipped=2) == "skipped"
    assert final_judge_mode("local", judged_cases=3, quota_skipped=0) == "local"


def test_fallback_rows_set_the_flag() -> None:
    assert fallback_used([{"fallback": False}, {"fallback": True}]) is True
    assert fallback_used([{"fallback": False}]) is False
    assert fallback_used([]) is False


async def test_a_quota_exhausted_judge_makes_the_run_skipped(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def act(task: JudgeTask) -> None:
        if task.inputs["case_id"] in {"law-0003", "law-0004"}:
            message = "quota"
            raise QuotaExhausted(message, transient=False)

    use_stub_judges(monkeypatch, SpyPool(act))
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    results = await go(dataset, tmp_path)
    assert results.manifest.judge_mode == "skipped"
    assert results.manifest.counts["judge_skipped"] > 0
    assert results.manifest.judged_cases > 0


async def test_a_drift_file_for_the_judge_sets_the_flag_not_the_fingerprint(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_stub_judges(monkeypatch, SpyPool())
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("PRUEFSTAND_CACHE_DIR", str(cache_dir))
    plain = await go(dataset, tmp_path)
    assert plain.manifest.judge_drift is False
    judge = synthetic_config(dataset, (Split.SMOKE,)).judge.pr.id
    (cache_dir / "judge_drift.json").write_text(
        json.dumps({"model": judge, "agreement": 0.7, "epoch": 1, "ts": "2026-11-03T02:00:00Z"}),
        encoding="utf-8",
    )
    drifted = await go(dataset, tmp_path)
    assert drifted.manifest.judge_drift is True
    assert drifted.manifest.eval_fingerprint == plain.manifest.eval_fingerprint
    (cache_dir / "judge_drift.json").write_text(
        json.dumps({"model": "other/judge", "agreement": 0.7, "epoch": 1, "ts": "t"}),
        encoding="utf-8",
    )
    other = await go(dataset, tmp_path)
    assert other.manifest.judge_drift is False
