import json
from pathlib import Path

import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_cases
from testsupport.runner_support import (
    SpyPool,
    charge_one,
    make_runner,
    registry_with_judged,
    run_cases,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import BudgetExceeded
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.models.run import RunArtifacts
from pruefstand.llm.budget import Budget
from pruefstand.store.artifacts import ArtifactStore


async def test_budget_exceeded_stops_the_run_and_keeps_finished_cases(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    budget = Budget(max_usd=0.045, max_tokens=None)

    async def charge(task: JudgeTask) -> None:
        charge_one(budget, cost_usd=0.01)  # the 5th charge passes 0.045 USD and raises

    runner = make_runner(
        adapter,
        metrics=registry_with_judged(),
        judges=SpyPool(charge),
        budget=budget,
        concurrency=1,
    )
    results = await run_cases(runner, make_cases(10))
    manifest = results.manifest
    assert manifest.complete is False
    assert manifest.stop_reason == "budget_exceeded"
    assert manifest.infra_error is None
    assert len(results.records) == 4
    assert [s.case.id for s in results.values] == [r.case_id for r in results.records]
    assert manifest.n_cases == 10
    assert manifest.counts["ok"] == 4
    assert manifest.cost.usd > 0.04
    assert manifest.cost.llm_calls == 5


async def test_budget_exceeded_from_a_judged_metric_is_not_swallowed(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))

    async def explode(task: JudgeTask) -> None:
        msg = "token budget exceeded"
        raise BudgetExceeded(msg)

    runner = make_runner(
        adapter, metrics=registry_with_judged(), judges=SpyPool(explode), concurrency=2
    )
    results = await run_cases(runner, make_cases(6))
    assert results.manifest.stop_reason == "budget_exceeded"
    assert results.manifest.complete is False
    assert results.manifest.counts.get("judge_error", 0) == 0


async def test_mark_aborted_rewrites_only_run_json(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    results = await run_cases(make_runner(adapter), make_cases(3))
    assert results.manifest.complete is True
    store = ArtifactStore(tmp_path)
    run_dir = store.write_run(
        RunArtifacts(results=results, root=tmp_path / results.manifest.run_id)
    )
    parquet_before = (run_dir / "results.parquet").read_bytes()

    store.mark_aborted(run_dir, "tunnel_lost: ssh exit 255")

    manifest = store.read_run(run_dir).results.manifest
    assert manifest.complete is False
    assert manifest.stop_reason == "aborted"
    assert manifest.infra_error == "tunnel_lost: ssh exit 255"
    assert (run_dir / "results.parquet").read_bytes() == parquet_before
    assert (
        json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["stop_reason"] == "aborted"
    )
    assert store.read_run(run_dir).results.records == results.records
