"""D1084: a hung target stops the run after N consecutive timeouts; nothing is dropped."""

import asyncio

import httpx
import pytest
import respx
from contract.adapter_contract import load_openapi_example
from pydantic import ValidationError
from testsupport.run_builders import make_cases
from testsupport.runner_support import make_runner, new_adapter, run_cases

from pruefstand.core.config import RunnerConfig
from pruefstand.runner.retry import is_timeout

NOT_RUN = "not run: stopped after 2 consecutive timeouts (runner.max_consecutive_timeouts)"


async def _hang(request: httpx.Request) -> httpx.Response:
    await asyncio.sleep(5)
    return httpx.Response(200, json=load_openapi_example("query_ok.json"))


async def test_hung_target_stops_after_n_timeouts_and_records_the_rest(
    router: respx.MockRouter,
) -> None:
    route = router.post("/v1/query").mock(side_effect=_hang)
    adapter = new_adapter(timeout_s=0.05)
    try:
        runner = make_runner(adapter, concurrency=1, max_retries=0, max_consecutive_timeouts=2)
        results = await run_cases(runner, make_cases(5))
    finally:
        await adapter.aclose()
    assert route.call_count + 0 <= 2  # respx counts completed calls; the two hangs never complete
    errors = [r.error for r in results.records]
    assert len(errors) == 5  # never silently dropped
    assert sum(is_timeout(e) for e in errors) == 2
    assert errors.count(NOT_RUN) == 3
    counts = results.manifest.counts
    assert (counts["error"], counts["timeout"], counts["aborted_after_timeouts"]) == (5, 2, 3)
    assert all(r.attempt == 0 for r in results.records if r.error == NOT_RUN)


async def test_a_success_resets_the_streak(router: respx.MockRouter) -> None:
    calls = 0

    async def alternate(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls % 2:
            await asyncio.sleep(5)
        return httpx.Response(200, json=load_openapi_example("query_ok.json"))

    router.post("/v1/query").mock(side_effect=alternate)
    adapter = new_adapter(timeout_s=0.05)
    try:
        runner = make_runner(adapter, concurrency=1, max_retries=0, max_consecutive_timeouts=2)
        results = await run_cases(runner, make_cases(6))
    finally:
        await adapter.aclose()
    assert calls == 6
    assert "aborted_after_timeouts" not in results.manifest.counts


@pytest.mark.parametrize("value", [0, -1])
def test_limit_must_be_positive_or_none(value: int) -> None:
    with pytest.raises(ValidationError):
        RunnerConfig(max_consecutive_timeouts=value)
    assert RunnerConfig().max_consecutive_timeouts is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("timeout after 360 s", True),
        ("POST /v1/query: timed out after 180s", True),
        ("POST /v1/retrieve: timed out after 0.05s", True),
        ("POST /v1/query: HTTP 504: upstream timed out after 30s", False),  # candidate text
        ("POST /v1/query: HTTP 503: timeout after 300 s", False),
        ("timeout after 360 s and more", False),
        (None, False),
    ],
)
def test_only_the_runner_and_adapter_timeout_texts_count(
    text: str | None,
    expected: bool,  # noqa: FBT001 - parametrized
) -> None:
    assert is_timeout(text) is expected
