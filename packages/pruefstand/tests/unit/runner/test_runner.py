import asyncio
import json
import re
from typing import Any

import httpx
import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_case, make_cases
from testsupport.runner_support import (
    SpyPool,
    make_runner,
    registry_with_judged,
    run_cases,
    values_of,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.metric import MetricStatus


class DictCache:
    """A real in-memory ``KVCache`` (the protocol is two methods)."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


def index_of(request: httpx.Request) -> int:
    match = re.search(r"Frage (\d+)", json.loads(request.content)["question"])
    assert match is not None
    return int(match.group(1))


def numbered(count: int, **changes: Any) -> list[Any]:
    return [make_case(i, question=f"Frage {i}: Kündigungsfrist?", **changes) for i in range(count)]


def echo_answer(request: httpx.Request) -> httpx.Response:
    body = load_example("query_ok.json")
    return httpx.Response(200, json={**body, "answer": f"Antwort {index_of(request)}"})


async def test_twenty_cases_all_ok_with_context_recall(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    cases = [
        make_case(i, gold_doc_ids=["gii-bgb-622" if i < 10 else "other-doc"]) for i in range(20)
    ]
    results = await run_cases(make_runner(adapter, concurrency=4), cases)
    assert len(results.records) == 20
    assert all(r.error is None and r.attempt == 1 and not r.cached for r in results.records)
    for i in range(20):
        recall = values_of(results, i)["context_recall"]
        assert recall.status is MetricStatus.OK
        assert recall.value == (1.0 if i < 10 else 0.0)
    assert results.manifest.complete is True
    assert results.manifest.stop_reason == "completed"
    assert results.manifest.counts["ok"] == 20
    assert results.manifest.counts.get("error", 0) == 0


async def test_order_follows_input_even_when_even_requests_are_slow(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    async def slow_even(request: httpx.Request) -> httpx.Response:
        if index_of(request) % 2 == 0:
            await asyncio.sleep(0.05)
        return echo_answer(request)

    router.post("/v1/query").mock(side_effect=slow_even)
    results = await run_cases(make_runner(adapter, concurrency=8), numbered(12))
    assert [r.case_id for r in results.records] == [f"law-{i:04d}" for i in range(12)]
    assert [s.case.id for s in results.values] == [f"law-{i:04d}" for i in range(12)]
    answers = [r.response.answer for r in results.records if r.response]
    assert answers == [f"Antwort {i}" for i in range(12)]


async def test_503_twice_then_200_is_attempt_three(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json=load_example("query_ok.json")),
    ]
    results = await run_cases(make_runner(adapter, concurrency=1), [make_case(0)])
    assert route.call_count == 3
    assert results.records[0].attempt == 3
    assert results.records[0].error is None
    assert values_of(results, 0)["error_rate"].value == 0.0


async def test_non_transient_error_is_not_retried_and_metrics_are_error(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(400, text="bad request")
    results = await run_cases(make_runner(adapter), [make_case(0)])
    assert route.call_count == 1
    record = results.records[0]
    assert record.response is None
    assert record.attempt == 1
    assert record.error is not None
    assert len(record.error) <= 500
    values = values_of(results, 0)
    assert values["error_rate"].value == 1.0
    assert values["error_rate"].status is MetricStatus.OK
    assert values["context_recall"].status is MetricStatus.ERROR
    assert values["context_recall"].value is None
    assert values["latency_ms"].status is MetricStatus.ERROR
    assert results.manifest.counts["error"] == 1
    assert results.manifest.complete is True


async def test_timeout_on_every_call_is_an_error_after_two_attempts(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=load_example("query_ok.json"))

    route = router.post("/v1/query").mock(side_effect=hang)
    runner = make_runner(adapter, timeout_s=0.05, max_retries=1)
    results = await run_cases(runner, [make_case(0)])
    assert route.call_count == 2
    assert results.records[0].attempt == 2
    assert results.records[0].error is not None
    assert values_of(results, 0)["error_rate"].value == 1.0


async def test_cache_hit_does_not_call_the_adapter(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    cache = DictCache()
    cases = make_cases(3)
    first = await run_cases(make_runner(adapter, cache=cache), cases)
    assert route.call_count == 3
    assert set(cache.data) == {
        stable_hash("fp-test", c.id, c.question, c.tenant) for c in cases
    }
    second = await run_cases(make_runner(adapter, cache=cache), cases)
    assert route.call_count == 3
    assert all(r.cached for r in second.records)
    assert second.manifest.counts["cached"] == 3
    assert [r.response for r in second.records] == [r.response for r in first.records]
    assert values_of(second, 0)["context_recall"] == values_of(first, 0)["context_recall"]


async def test_errors_are_never_cached(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(400)
    cache = DictCache()
    await run_cases(make_runner(adapter, cache=cache), [make_case(0)])
    assert cache.data == {}


async def test_manifest_carries_what_the_runner_knows(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    results = await run_cases(make_runner(adapter), make_cases(3))
    manifest = results.manifest
    assert re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{6}", manifest.run_id)
    assert manifest.n_cases == 3
    assert manifest.seed == 7
    assert manifest.target_fingerprint == "fp-test"
    assert manifest.duration_s >= 0
    assert [s.value for s in manifest.splits] == ["core"]
    assert manifest.metric_versions["context_recall"] == "1"
    assert manifest.infra_error is None
    assert manifest.judge_mode == "skipped"


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


async def test_oversized_answer_surfaces_the_truncation_warning(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body = {**load_example("query_ok.json"), "answer": "Kündigung " * 3000}
    router.post("/v1/query").respond(200, json=body)
    results = await run_cases(make_runner(adapter), [make_case(0)])
    assert results.manifest.counts["metric_truncated"] >= 1
    assert any(v.details.get("truncated") for v in results.values[0].values)


async def test_cancellation_returns_an_aborted_run_with_the_finished_cases(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    async def slow_after_three(request: httpx.Request) -> httpx.Response:
        if index_of(request) >= 3:
            await asyncio.sleep(30)
        return echo_answer(request)

    router.post("/v1/query").mock(side_effect=slow_after_three)
    runner = make_runner(adapter, concurrency=8)
    task = asyncio.create_task(run_cases(runner, numbered(8)))
    await asyncio.sleep(0.3)
    task.cancel()
    results = await task
    assert results.manifest.complete is False
    assert results.manifest.stop_reason == "aborted"
    assert results.manifest.infra_error is None
    assert [r.case_id for r in results.records] == ["law-0000", "law-0001", "law-0002"]
    assert results.manifest.n_cases == 8


# --- robust_pr via /v1/retrieve (R11 D218, D222) ---------------------------------------------------


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


# --- judged subset (R12 N1.2, R13 P3.4) ------------------------------------------------------------


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


