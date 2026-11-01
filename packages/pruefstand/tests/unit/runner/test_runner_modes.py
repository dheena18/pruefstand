from typing import Any

import httpx
import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_case
from testsupport.runner_support import (
    DictCache,
    SpyPool,
    index_of,
    make_runner,
    numbered,
    registry_with_judged,
    run_cases,
    values_of,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.models.metric import MetricStatus

# --- robust_pr via /v1/retrieve (R11 D218, D222) ---------------------------------------------


def mixed_cases() -> list[Any]:
    robust = [
        make_case(i, split="robust_pr", question=f"Frage {i}: Kündigungsfrist?") for i in range(3)
    ]
    core = [make_case(i, question=f"Frage {i}: Kündigungsfrist?") for i in range(3, 5)]
    return [*robust, *core]


async def test_robust_pr_cases_use_retrieve_only(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    retrieve = router.post("/v1/retrieve").respond(200, json=load_example("retrieve_ok.json"))
    query = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    results = await run_cases(make_runner(adapter), mixed_cases())
    assert retrieve.call_count == 3
    assert query.call_count == 2
    for i in range(3):
        record = results.records[i]
        assert record.mode == "retrieve"
        assert record.response is not None
        assert record.response.answer == ""
        assert record.response.chunks
        values = values_of(results, i)
        assert values["language_match"].status is MetricStatus.NOT_APPLICABLE
        assert values["language_match"].value is None
        assert values["context_recall"].status is MetricStatus.OK
        assert values["error_rate"].value == 0.0
    assert [results.records[i].mode for i in (3, 4)] == ["answer", "answer"]
    assert results.manifest.counts["retrieve"] == 3
    assert results.manifest.counts.get("retrieve_fallback", 0) == 0


async def test_retrieve_404_falls_back_to_query(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/retrieve").respond(404)
    query = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    results = await run_cases(make_runner(adapter), mixed_cases())
    assert query.call_count == 5
    assert all(r.mode == "answer" for r in results.records)
    assert results.manifest.counts["retrieve_fallback"] == 3
    assert results.manifest.counts.get("retrieve", 0) == 0
    assert values_of(results, 0)["language_match"].status is MetricStatus.OK


async def test_cache_entry_of_the_other_mode_is_a_miss(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    retrieve = router.post("/v1/retrieve").respond(200, json=load_example("retrieve_ok.json"))
    cache = DictCache()
    await run_cases(make_runner(adapter, cache=cache), [make_case(0)])  # answer-mode entry
    results = await run_cases(make_runner(adapter, cache=cache), [make_case(0, split="robust_pr")])
    assert retrieve.call_count == 1
    assert results.records[0].mode == "retrieve"
    assert results.records[0].cached is False


# --- judged subset (R12 N1.2, R13 P3.4) ------------------------------------------------------


async def test_judged_subset_limits_judging_and_generation(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    retrieve = router.post("/v1/retrieve").respond(200, json=load_example("retrieve_ok.json"))
    query = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    in_subset = [make_case(i, judged_subset=True, question=f"Frage {i}?") for i in range(4)]
    outside = [make_case(i, question=f"Frage {i}?") for i in range(4, 8)]
    injection = [
        make_case(i, category="injection", injection_marker="PWNED-4711", question=f"Frage {i}?")
        for i in range(8, 10)
    ]
    cases = [*in_subset, *outside, *injection]
    pool = SpyPool()
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool, concurrency=1)
    results = await run_cases(runner, cases, judged_subset=True)

    assert len(pool.score_calls) == 4
    assert retrieve.call_count == 4  # the 4 core answerable cases outside the subset
    assert query.call_count == 6  # 4 subset cases + 2 injection cases
    for i in range(4, 8):
        assert results.records[i].mode == "retrieve"
        values = values_of(results, i)
        assert values["faithfulness"].status is MetricStatus.NOT_APPLICABLE
        assert values["faithfulness"].details["reason"] == "not_in_judged_subset"
        assert values["language_match"].details["reason"] == "not_in_judged_subset"
        assert values["context_recall"].status is MetricStatus.OK
    for i in (8, 9):
        assert results.records[i].mode == "answer"
        values = values_of(results, i)
        assert values["injection_success"].status is MetricStatus.OK
        assert values["faithfulness"].details["reason"] == "not_in_judged_subset"
    assert results.manifest.counts.get("judge_skipped", 0) == 0
    assert results.manifest.judged_subset is True
    assert results.manifest.judged_cases == 4


async def test_without_the_flag_every_case_is_generated_and_judged(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    cases = [make_case(i, judged_subset=i < 4, question=f"Frage {i}?") for i in range(10)]
    pool = SpyPool()
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool)
    results = await run_cases(runner, cases)
    assert len(pool.score_calls) == 10
    assert all(r.mode == "answer" for r in results.records)
    assert results.manifest.judged_subset is False


async def test_hard_fail_case_skips_the_judges_and_keeps_deterministic_values(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        name = "query_other_tenant.json" if index_of(request) == 2 else "query_ok.json"
        return httpx.Response(200, json=load_example(name))

    router.post("/v1/query").mock(side_effect=respond)
    pool = SpyPool()
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool, concurrency=1)
    results = await run_cases(runner, numbered(5))
    assert values_of(results, 2)["tenant_leak"].value == 1.0
    assert values_of(results, 0)["tenant_leak"].value == 0.0
    assert sorted(pool.score_calls) == ["law-0000", "law-0001", "law-0003", "law-0004"]
    skipped = values_of(results, 2)["faithfulness"]
    assert skipped.status is MetricStatus.NOT_APPLICABLE
    assert skipped.details["reason"] == "hard_fail"
    assert values_of(results, 0)["faithfulness"].status is MetricStatus.OK
    assert results.manifest.judged_cases == 4


async def test_failed_request_costs_no_judge_call(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(400)
    pool = SpyPool()
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=pool)
    results = await run_cases(runner, [make_case(0)])
    assert pool.for_metric_calls == []
    assert values_of(results, 0)["faithfulness"].status is MetricStatus.ERROR


async def test_judged_metrics_are_not_applicable_without_judges(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    runner = make_runner(adapter, metrics=registry_with_judged(), judges=None)
    results = await run_cases(runner, [make_case(0)])
    value = values_of(results, 0)["faithfulness"]
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.details["reason"] == "no_judges"
    assert results.manifest.judged_cases == 0
