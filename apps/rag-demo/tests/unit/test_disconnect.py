"""Client disconnect cancels the upstream generator call (T3.6a, D624).

The real FastAPI app runs under a real uvicorn on loopback; the generator talks to a real
loopback server that never answers and records whether the app closed the upstream connection.
Every wait is on an event (no sleeps as assertions); the timeouts only guard against a hang.
"""

import asyncio
import re
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from rd_support import CONFIGS, qdrant_point
from starlette.requests import Request
from starlette.types import Message

from rag_demo.api import create_app
from rag_demo.config import Settings, load_config
from rag_demo.disconnect import cancel_on_disconnect
from rag_demo.errors import ClientDisconnectedError
from rag_demo.wiring import expected_fingerprint

GUARD_S = 15.0  # a hang guard, never a latency assertion
CFG = load_config(CONFIGS / "rag.yaml")
QDRANT = "http://qdrant.test:6333/collections/chunks_active"
CHUNKS = ["gii-bgb-622#1", "gii-kschg-1#0"]


class SilentUpstream:
    """A loopback server that reads one request, never replies and notes when the peer closes."""

    def __init__(self) -> None:
        self.received = asyncio.Event()
        self.closed = asyncio.Event()
        self.requests = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = int(re.search(rb"content-length: (\d+)", head, re.IGNORECASE).group(1))  # type: ignore[union-attr]  # test input
        await reader.readexactly(length)
        self.requests += 1
        self.received.set()
        with suppress(ConnectionError):
            while await reader.read(4096):
                pass  # the request is queued upstream until the peer goes away
        self.closed.set()
        writer.close()


@pytest.fixture
async def upstream() -> AsyncIterator[tuple[SilentUpstream, str]]:
    fake = SilentUpstream()
    url = await fake.start()
    yield fake, url
    await fake.stop()


def _mock_retrieval() -> None:
    meta = {
        "corpus_version": "fixture-1",
        "tenants": ["kanzlei_mueller", "shared_public"],
        "analyzer": expected_fingerprint(CFG),
        "complete": True,
    }
    respx.get(QDRANT).mock(
        return_value=httpx.Response(200, json={"result": {"config": {"metadata": meta}}})
    )
    respx.post("http://embed:8090/embed").mock(
        return_value=httpx.Response(200, json=[[0.01] * CFG.embed.dim])
    )
    points = [qdrant_point(cid, 0.3 - i * 0.01) for i, cid in enumerate(CHUNKS)]
    respx.post(f"{QDRANT}/points/query").mock(
        return_value=httpx.Response(200, json={"result": {"points": points}})
    )


async def _serve(app: Any) -> tuple[uvicorn.Server, asyncio.Task[None], str]:
    """Serve ``app`` on a pre-bound loopback socket: connections wait in the backlog until ready."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    return server, task, f"http://127.0.0.1:{sock.getsockname()[1]}"


@respx.mock
async def test_a_client_that_hangs_up_closes_the_upstream_generator_call(
    upstream: tuple[SilentUpstream, str],
) -> None:
    fake, llm_url = upstream
    respx.route(host="127.0.0.1").pass_through()
    _mock_retrieval()
    settings = Settings(
        qdrant_url="http://qdrant.test:6333", llm_url=llm_url, embed_url="http://embed:8090"
    )
    server, serving, app_url = await _serve(create_app(CFG, settings=settings))
    body = {"tenant_id": "kanzlei_mueller", "question": "Welche Frist gilt?", "request_id": "r-1"}
    try:
        async with httpx.AsyncClient() as client:
            call = asyncio.create_task(client.post(f"{app_url}/v1/query", json=body, timeout=60))
            await asyncio.wait_for(fake.received.wait(), GUARD_S)
            assert not fake.closed.is_set()  # the generation is running upstream
            call.cancel()  # the runner gives up and drops its connection
            with suppress(asyncio.CancelledError):
                await call
        await asyncio.wait_for(fake.closed.wait(), GUARD_S)
    finally:
        server.should_exit = True
        await serving
    assert fake.requests == 1  # no retry of the cancelled call


def _request(receive: Callable[[], Awaitable[Message]]) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)


async def test_work_that_finishes_returns_its_result_and_stops_listening() -> None:
    never = asyncio.Event()

    async def receive() -> Message:
        await never.wait()
        return {"type": "http.disconnect"}

    async def work() -> int:
        return 5

    assert await cancel_on_disconnect(_request(receive), work()) == 5


async def test_an_error_of_the_work_propagates() -> None:
    never = asyncio.Event()

    async def receive() -> Message:
        await never.wait()
        return {"type": "http.disconnect"}

    async def work() -> int:
        msg = "boom"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="boom"):
        await cancel_on_disconnect(_request(receive), work())


async def test_a_disconnect_cancels_the_work_and_raises() -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()
    hang_up = asyncio.Event()

    async def receive() -> Message:
        await hang_up.wait()
        return {"type": "http.disconnect"}

    async def work() -> int:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 1

    task = asyncio.create_task(cancel_on_disconnect(_request(receive), work()))
    await asyncio.wait_for(started.wait(), GUARD_S)
    hang_up.set()
    with pytest.raises(ClientDisconnectedError):
        await asyncio.wait_for(task, GUARD_S)
    assert cancelled.is_set()
