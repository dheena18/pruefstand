"""Target-cache behaviour of the runner: planted rows, failing caches (review of PR 21)."""

import pickle
import sqlite3
from pathlib import Path

import respx
from contract.adapter_contract import load_example
from testsupport.run_builders import make_case, make_cases
from testsupport.runner_support import DictCache, make_runner, run_cases

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import StoreError
from pruefstand.core.hashing import stable_hash
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
