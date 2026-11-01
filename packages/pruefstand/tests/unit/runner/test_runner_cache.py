"""Target-cache behaviour of the runner: planted rows, failing caches (review of PR 21)."""

import json
import pickle
import sqlite3
from pathlib import Path

import pytest
import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_case, make_cases, unhashed
from testsupport.runner_support import DictCache, make_runner, run_cases

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import StoreError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.kv import DiskKVCache


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


async def test_a_planted_integer_row_in_a_real_disk_cache_is_a_miss(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path
) -> None:
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


_GOOD = {"answer": "Ein Monat.", "citations": []}


def _entry(**changes: object) -> bytes:
    body = {"mode": "answer", "latency_ms": 12.5, "response": _GOOD, **changes}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


PLANTED = {
    "deep_nesting": b"[" * 200000,
    "huge_latency": (
        '{"mode":"answer","latency_ms":' + "9" * 400 + ',"response":{"answer":"x"}}'
    ).encode(),
    "nan_latency": b'{"mode":"answer","latency_ms":NaN,"response":{"answer":"x"}}',
    "infinite_latency": b'{"mode":"answer","latency_ms":1e999,"response":{"answer":"x"}}',
    "negative_latency": _entry(latency_ms=-1.0),
    "lone_surrogate": b'{"mode":"answer","latency_ms":1.0,"response":{"answer":"x\\ud800y"}}',
    "extra_field": _entry(unexpected=1),
    "nan_score": (
        b'{"mode":"answer","latency_ms":1.0,"response":{"answer":"x","chunks":[{"chunk_id":"c",'
        b'"doc_id":"d","text":"t","score":NaN,"rank":1}]}}'
    ),
    "infinite_score": (
        b'{"mode":"answer","latency_ms":1.0,"response":{"answer":"x","chunks":[{"chunk_id":"c",'
        b'"doc_id":"d","text":"t","score":1e999,"rank":1}]}}'
    ),
}


@pytest.mark.parametrize("name", sorted(PLANTED))
async def test_planted_cache_entries_are_misses_and_the_run_stays_writable(
    router: respx.MockRouter, adapter: HttpTargetAdapter, tmp_path: Path, name: str
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    case = make_case(0)
    cache = DictCache()
    cache.set(stable_hash("fp-test", case.id, case.question, case.tenant), PLANTED[name])
    results = await run_cases(make_runner(adapter, cache=cache), [case])
    assert route.call_count == 1
    assert results.records[0].cached is False
    store = ArtifactStore(tmp_path)
    path = store.write_run(RunArtifacts(results=results, root=tmp_path / results.manifest.run_id))
    assert unhashed(store.read_run(path).results) == results


class _CountingBrokenCache:
    def __init__(self) -> None:
        self.gets = 0
        self.sets = 0

    def get(self, key: str) -> bytes | None:
        self.gets += 1
        msg = "database is locked"
        raise StoreError(msg)

    def set(self, key: str, value: bytes) -> None:
        self.sets += 1
        msg = "database is locked"
        raise StoreError(msg)


async def test_a_failing_cache_is_skipped_after_the_first_failure(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    cache = _CountingBrokenCache()
    results = await run_cases(make_runner(adapter, cache=cache, concurrency=1), make_cases(6))
    assert results.manifest.complete is True
    assert cache.gets == 1
    assert cache.sets == 0
