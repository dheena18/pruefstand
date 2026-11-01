import asyncio

import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_cases
from testsupport.runner_support import (
    SpyPool,
    charge_one,
    make_runner,
    registry_with_judged,
    run_cases,
    values_of,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import LLMError, PolicyViolation, QuotaExhausted
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.models.metric import MetricStatus
from pruefstand.llm.budget import Budget


def failing(case_ids: set[str], error: Exception) -> SpyPool:
    async def act(task: JudgeTask) -> None:
        if task.inputs["case_id"] in case_ids:
            raise error

    return SpyPool(act)


async def test_one_judge_failure_in_twenty_is_an_error_value_but_not_degraded(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    pool = failing({"law-0007"}, LLMError("judge down", transient=True))
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool)
    results = await run_cases(runner, make_cases(20))
    bad = values_of(results, 7)["faithfulness"]
    assert bad.status is MetricStatus.ERROR
    assert bad.value is None
    assert bad.details["error"] == "LLMError"
    assert (
        sum(values_of(results, i)["faithfulness"].status is MetricStatus.OK for i in range(20))
        == 19
    )
    assert results.manifest.counts["judge_error"] == 1
    assert results.manifest.judge_degraded is False  # 1/20 = 5 %, not more than 5 %
    assert results.manifest.complete is True
    assert results.manifest.judged_cases == 20


async def test_two_judge_failures_in_twenty_degrade_the_judge(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    pool = failing({"law-0003", "law-0004"}, LLMError("judge down", transient=True))
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool)
    results = await run_cases(runner, make_cases(20))
    assert results.manifest.counts["judge_error"] == 2
    assert results.manifest.judge_degraded is True


async def test_policy_violation_is_counted_like_an_llm_error(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    pool = failing({"law-0001"}, PolicyViolation("provider not allowed"))
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool)
    results = await run_cases(runner, make_cases(4))
    value = values_of(results, 1)["faithfulness"]
    assert value.status is MetricStatus.ERROR
    assert value.details["error"] == "PolicyViolation"
    assert results.manifest.counts["judge_error"] == 1


async def test_quota_exhausted_stops_judging_for_the_rest_of_the_run(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    pool = failing({"law-0002"}, QuotaExhausted("429", transient=False))
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool, concurrency=1)
    results = await run_cases(runner, make_cases(20))
    assert len(pool.score_calls) == 3
    for i in range(2):
        assert values_of(results, i)["faithfulness"].status is MetricStatus.OK
    for i in range(2, 20):
        value = values_of(results, i)["faithfulness"]
        assert value.status is MetricStatus.NOT_APPLICABLE
        assert value.details["reason"] == "judge_quota"
    assert results.manifest.counts["judge_skipped"] == 18
    assert results.manifest.counts.get("judge_error", 0) == 0
    assert results.manifest.judge_degraded is False
    assert results.manifest.complete is True


async def test_request_cap_leaves_one_request_unused_at_concurrency_one(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    budget = Budget(max_usd=0, max_tokens=None, max_requests=4)

    async def one_request(task: JudgeTask) -> None:
        charge_one(budget)

    pool = SpyPool(one_request)
    runner = make_runner(
        adapter, metrics=registry_with_judged(), judges=pool, budget=budget, concurrency=1
    )
    results = await run_cases(runner, make_cases(20))
    assert len(pool.score_calls) == 3  # the 4th reservation of 2 would pass the cap of 4
    assert results.manifest.complete is True
    assert results.manifest.counts["judge_skipped"] == 17
    skipped = values_of(results, 10)["faithfulness"]
    assert skipped.status is MetricStatus.NOT_APPLICABLE
    assert skipped.details["reason"] == "judge_cap"
    assert budget.requests_remaining == 1  # every reservation was released


async def test_request_cap_holds_at_concurrency_eight_with_repairs(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    budget = Budget(max_usd=0, max_tokens=None, max_requests=4)

    async def needs_repair(task: JudgeTask) -> None:
        charge_one(budget)
        await asyncio.sleep(0.01)  # keep the reservations overlapping
        charge_one(budget)  # the complete_json repair

    pool = SpyPool(needs_repair)
    runner = make_runner(
        adapter, metrics=registry_with_judged(), judges=pool, budget=budget, concurrency=8
    )
    results = await run_cases(runner, make_cases(20))
    assert results.manifest.complete is True
    assert results.manifest.stop_reason == "completed"
    assert len(pool.score_calls) == 2
    assert results.manifest.counts["judge_skipped"] == 18
    assert budget.requests_remaining == 0
    reasons = [values_of(results, i)["faithfulness"].details.get("reason") for i in range(20)]
    assert reasons.count("judge_cap") == 18
    assert results.manifest.cost.llm_calls == 4
