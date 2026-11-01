import asyncio
import pickle
import re
from pathlib import Path

import httpx
import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_case, make_cases
from testsupport.runner_support import (
    DictCache,
    echo_answer,
    index_of,
    make_runner,
    numbered,
    run_cases,
    values_of,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import StoreError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunArtifacts
from pruefstand.core.models.target import TargetResponse
from pruefstand.runner.retry import Attempts
from pruefstand.runner.runner import case_rng
from pruefstand.runner.target_call import _require_valid_unicode
from pruefstand.store.artifacts import ArtifactStore


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
    started: list[int] = []

    async def hang(request: httpx.Request) -> httpx.Response:
        started.append(1)  # respx records a call only when it completes; count the starts
        await asyncio.sleep(5)
        return httpx.Response(200, json=load_example("query_ok.json"))

    router.post("/v1/query").mock(side_effect=hang)
    runner = make_runner(adapter, timeout_s=0.05, max_retries=1)
    results = await run_cases(runner, [make_case(0)])
    assert len(started) == 2
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
    assert set(cache.data) == {stable_hash("fp-test", c.id, c.question, c.tenant) for c in cases}
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


async def test_no_cases_is_a_complete_empty_run(adapter: HttpTargetAdapter) -> None:
    results = await run_cases(make_runner(adapter), [])
    assert results.records == ()
    assert results.values == ()
    assert results.manifest.complete is True
    assert results.manifest.n_cases == 0


class _Evil:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[object, tuple[str, str]]:
        return (open, (str(self.marker), "w"))


async def test_a_planted_pickle_in_the_cache_is_a_miss_and_never_executed(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    marker = tmp_path / "pwned"
    case = make_case(0)
    cache = DictCache()
    cache.set(
        stable_hash("fp-test", case.id, case.question, case.tenant), pickle.dumps(_Evil(marker))
    )
    results = await run_cases(make_runner(adapter, cache=cache), [case])
    assert route.call_count == 1
    assert results.records[0].cached is False
    assert not marker.exists()


class _BrokenCache:
    """A cache whose every call fails (read-only mount, corrupt file)."""

    def get(self, key: str) -> bytes | None:
        msg = "cache unreadable"
        raise StoreError(msg)

    def set(self, key: str, value: bytes) -> None:
        msg = "cache is read-only"
        raise StoreError(msg)


async def test_cache_failures_are_misses_not_run_aborts(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    results = await run_cases(make_runner(adapter, cache=_BrokenCache()), make_cases(4))
    assert route.call_count == 4
    assert results.manifest.complete is True
    assert results.manifest.counts["ok"] == 4


def test_negative_and_positive_seeds_give_different_streams() -> None:
    assert case_rng(5, 0).random() != case_rng(-5, 0).random()
    assert case_rng(5, 0).random() == case_rng(5, 0).random()
    assert case_rng(5, 0).random() != case_rng(5, 1).random()


async def test_a_response_with_a_lone_surrogate_is_a_target_error_and_the_run_is_writable(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path
) -> None:
    body = b'{"answer": "x\\ud800y", "citations": []}'
    router.post("/v1/query").respond(
        200, content=body, headers={"content-type": "application/json"}
    )
    cache = DictCache()
    results = await run_cases(make_runner(adapter, cache=cache), [make_case(0)])
    assert results.records[0].response is None
    assert results.records[0].error is not None
    assert cache.data == {}
    store = ArtifactStore(tmp_path)
    path = store.write_run(RunArtifacts(results=results, root=tmp_path / results.manifest.run_id))
    assert store.read_run(path).results == results


def test_a_response_that_cannot_be_encoded_becomes_a_target_error() -> None:

    bad = TargetResponse.model_validate({"answer": "x\ud800y"})
    out = _require_valid_unicode(Attempts(bad, None, 2))
    assert out.value is None
    assert out.error is not None
    assert "unicode" in out.error
    assert out.attempts == 2
    good = Attempts(TargetResponse(answer="Kündigung"), None, 1)
    assert _require_valid_unicode(good) is good


async def test_a_planted_integer_row_in_a_real_disk_cache_is_a_miss(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path
) -> None:
    import sqlite3

    from pruefstand.store.kv import DiskKVCache

    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    case = make_case(0)
    key = stable_hash("fp-test", case.id, case.question, case.tenant)
    with DiskKVCache(tmp_path, "target"):
        pass
    db = sqlite3.connect(tmp_path / "target" / "cache.sqlite3")
    db.execute("DROP TABLE kv")
    db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value)")
    db.execute("INSERT INTO kv VALUES (?, ?)", (key, 3_000_000_000))
    db.commit()
    db.close()
    with DiskKVCache(tmp_path, "target") as cache:
        results = await run_cases(make_runner(adapter, cache=cache), [case])
    assert route.call_count == 1
    assert results.manifest.complete is True
