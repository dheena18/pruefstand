"""Review round 1: bounded parsing, tolerant third-party responses, error hygiene (T1.3)."""

import asyncio
import subprocess
import sys
import textwrap
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import respx
from contract.adapter_contract import load_example

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

BASE = "http://target.test"
REQ = TargetRequest(tenant_id=TenantId("public"), question="Frage", top_k=None, request_id="c-1")
CHUNK = {"chunk_id": "c", "doc_id": "d", "text": "t", "score": 0.5, "rank": 1}


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=5))
    yield instance
    await instance.aclose()


def bomb(items: int = 4_000_000) -> bytes:
    return b'{"answer":"x","citations":[' + b"1," * items + b"1]}"


# ---- M1: memory / CPU bounds ------------------------------------------------------------


async def test_citations_bomb_is_rejected_fast_and_permanently(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, content=bomb())
    started = time.monotonic()
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert time.monotonic() - started < 2.0
    assert excinfo.value.transient is False


def test_citations_bomb_stays_within_a_memory_budget() -> None:
    script = textwrap.dedent(
        """
        import asyncio, resource, respx
        from pruefstand.adapters.http import HttpTargetAdapter
        from pruefstand.core.config import HttpTargetConfig
        from pruefstand.core.errors import TargetError
        from pruefstand.core.models.target import TargetRequest

        body = b'{"answer":"x","citations":[' + b"1," * 4_000_000 + b"1]}"

        async def main():
            req = TargetRequest(tenant_id="t", question="q", top_k=None, request_id="r")
            with respx.mock(base_url="http://target.test") as mock:
                mock.post("/v1/query").respond(200, content=body)
                adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url="http://target.test"))
                before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                try:
                    await adapter.query(req)
                except TargetError:
                    pass
                await adapter.aclose()
                print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before)

        asyncio.run(main())
        """
    )
    result = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-I", "-c", script], check=True, capture_output=True, text=True
    )
    assert int(result.stdout.strip()) < 300 * 1024  # KiB; the unbounded version used > 3 GiB


async def test_event_loop_keeps_ticking_while_a_bomb_is_parsed(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, content=bomb())
    gaps: list[float] = []

    async def ticker() -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    with pytest.raises(TargetError):
        await adapter.query(REQ)
    task.cancel()
    assert gaps
    assert max(gaps) < 0.5


@pytest.mark.parametrize(
    ("citations", "ok"),
    [(["§ 1"] * 1000, True), (["§ 1"] * 1001, False), ([1] * 1001, False), ("§ 1", False)],
)
async def test_citation_bounds_and_types(
    router: respx.MockRouter,
    adapter: HttpTargetAdapter,
    citations: object,
    ok: bool,  # noqa: FBT001
) -> None:
    router.post("/v1/query").respond(200, json={"answer": "a", "citations": citations})
    if ok:
        assert len((await adapter.query(REQ)).citations) == 1000
    else:
        with pytest.raises(TargetError) as excinfo:
            await adapter.query(REQ)
        assert excinfo.value.transient is False


async def test_too_many_chunks_are_rejected(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    chunks = [{**CHUNK, "rank": i + 1} for i in range(10_001)]
    router.post("/v1/query").respond(200, json={"answer": "a", "chunks": chunks})
    with pytest.raises(TargetError, match="chunks"):
        await adapter.query(REQ)


async def test_many_invalid_chunks_give_a_short_message(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json={"answer": "a", "chunks": [{}] * 5000})
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert len(str(excinfo.value)) < 500


# ---- M2: tolerant of ordinary third-party responses ---------------------------------------


async def test_unknown_keys_and_null_optionals_are_tolerated(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body: dict[str, Any] = {
        "answer": "Antwort",
        "citations": None,
        "chunks": [{**CHUNK, "metadata": {"page": 3}, "tenant_id": None, "used_in_prompt": None}],
        "refused": None,
        "model": None,
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        "request_id": "echoed",
        "latency_ms": 12.5,
    }
    router.post("/v1/query").respond(200, json=body)
    response = await adapter.query(REQ)
    assert response.citations == ()
    assert response.usage is not None
    assert response.usage.completion_tokens == 4
    assert response.chunks is not None
    assert response.chunks[0].tenant_id is None


async def test_usage_without_token_counts_is_treated_as_absent(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json={"answer": "a", "usage": {"total_tokens": 7}})
    assert (await adapter.query(REQ)).usage is None


@pytest.mark.parametrize(
    "body",
    [
        {"answer": 5},
        {"answer": "a", "chunks": [{**CHUNK, "score": "high"}]},
        {"answer": "a", "chunks": "none"},
        {"answer": "a", "usage": {"prompt_tokens": "x", "completion_tokens": 1}},
        {"answer": "a", "refused": "maybe"},
    ],
)
async def test_type_errors_in_known_fields_stay_strict(
    router: respx.MockRouter, adapter: HttpTargetAdapter, body: dict[str, Any]
) -> None:
    router.post("/v1/query").respond(200, json=body)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False


async def test_retrieve_tolerates_extras_but_not_an_answer(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/retrieve").respond(
        200, json={"chunks": [{**CHUNK, "metadata": {}}], "took_ms": 3, "request_id": "x"}
    )
    response = await adapter.retrieve(REQ)
    assert response is not None
    assert len(response.chunks) == 1
    route.respond(200, json={"chunks": [], "answer": "no"})
    with pytest.raises(TargetError, match="answer"):
        await adapter.retrieve(REQ)


async def test_info_tolerates_extras_and_null_serving(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body = {**load_example("info.json"), "uptime_s": 12, "serving": None}
    router.get("/v1/info").respond(200, json=body)
    info = await adapter.info()
    assert info is not None
    assert info.serving == {}
