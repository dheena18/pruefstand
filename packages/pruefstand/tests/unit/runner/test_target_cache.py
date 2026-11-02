"""The target cache keyed by ``target_fingerprint`` (T6.1 S1): what invalidates it."""

from pathlib import Path
from typing import Any

import respx
from contract.adapter_contract import load_openapi_example
from testsupport.run_builders import make_cases
from testsupport.runner_support import make_runner, new_adapter

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.fingerprint import target_fingerprint
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.store.kv import DiskKVCache, build_cache

URL = "http://target.test"


def info(**changes: Any) -> TargetInfo:
    data: dict[str, Any] = {
        "app_version": "0.1",
        "git_sha": "abc123",
        "image_digest": None,
        "config_hash": "cfg",
        "corpus_version": "2026-11-02.ab12cd34",
        "models": {"generator": "g1"},
        "serving": {"engine": "ollama", "engine_version": "0.9.0"},
    }
    return TargetInfo.model_validate({**data, **changes})


async def run_once(
    router: respx.MockRouter, cache_dir: Path, target: TargetInfo, count: int = 3
) -> tuple[RunResults, int]:
    route = router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    adapter: HttpTargetAdapter = new_adapter()
    try:
        with DiskKVCache(cache_dir, "target") as cache:
            fingerprint = target_fingerprint(target, url=URL, run_id="r")
            results = await make_runner(adapter, cache=cache).run(
                make_cases(count), target_fingerprint=fingerprint, seed=1
            )
    finally:
        await adapter.aclose()
    return results, route.call_count


async def test_the_same_fingerprint_twice_makes_no_adapter_call(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    first, first_calls = await run_once(router, tmp_path, info())
    router.reset()
    second, second_calls = await run_once(router, tmp_path, info())
    assert first_calls == 3
    assert second_calls == 0
    assert all(r.cached for r in second.records)
    assert second.manifest.counts["cached"] == 3
    assert not any(r.cached for r in first.records)


async def test_a_new_app_git_sha_requeries_every_case(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    await run_once(router, tmp_path, info())
    router.reset()
    second, calls = await run_once(router, tmp_path, info(git_sha="def456"))
    assert calls == 3
    assert not any(r.cached for r in second.records)


async def test_a_changed_serving_field_requeries_every_case(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    await run_once(router, tmp_path, info())
    router.reset()
    serving = {"engine": "ollama", "engine_version": "0.9.1"}
    second, calls = await run_once(router, tmp_path, info(serving=serving))
    assert calls == 3
    assert not any(r.cached for r in second.records)


async def test_a_pr_overlay_reads_main_and_never_writes_it(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    await run_once(router, tmp_path / "shared", info())
    before = (tmp_path / "shared" / "target" / "cache.sqlite3").read_bytes()
    router.reset()
    route = router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    adapter = new_adapter()
    try:
        with build_cache("overlay", tmp_path / "shared", tmp_path / "overlay") as cache:
            fp = target_fingerprint(info(), url=URL, run_id="r")
            hit = await make_runner(adapter, cache=cache).run(
                make_cases(3), target_fingerprint=fp, seed=1
            )
            fp2 = target_fingerprint(info(git_sha="pr-head"), url=URL, run_id="r")
            miss = await make_runner(adapter, cache=cache).run(
                make_cases(3), target_fingerprint=fp2, seed=1
            )
    finally:
        await adapter.aclose()
    assert all(r.cached for r in hit.records)
    assert not any(r.cached for r in miss.records)
    assert route.call_count == 3
    assert (tmp_path / "shared" / "target" / "cache.sqlite3").read_bytes() == before
