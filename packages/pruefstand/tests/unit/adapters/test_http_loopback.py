"""Plumbing tests against a real loopback socket (no model or target is simulated, ADR-0008).

The server only misbehaves at the transport level (drip, endless chunked body, reset); it never
pretends to be a RAG system.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from pruefstand.adapters.http import MAX_RESPONSE_BYTES, HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

REQ = TargetRequest(tenant_id=TenantId("public"), question="Frage", top_k=None, request_id="c-1")
Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def _read_request(reader: asyncio.StreamReader) -> None:
    head = await reader.readuntil(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    await reader.readexactly(length)


async def _serve(handler: Handler) -> tuple[asyncio.Server, str]:
    async def wrapped(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await _read_request(reader)
            await handler(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(wrapped, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[Handler], Awaitable[str]]]:
    servers: list[asyncio.Server] = []

    async def start(handler: Handler) -> str:
        server, url = await _serve(handler)
        servers.append(server)
        return url

    yield start
    for server in servers:
        server.close()


async def test_slow_drip_over_a_real_socket_hits_the_total_deadline(
    serve: Callable[[Handler], Awaitable[str]],
) -> None:
    async def drip(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        for _i in range(100):
            writer.write(b" ")
            await writer.drain()
            await asyncio.sleep(0.1)

    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=await serve(drip), timeout_s=0.6))
    started = time.monotonic()
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert excinfo.value.transient is False  # D624: a read timeout is never retried
    # The deadline is 0.6 s; the drip would last 10 s. Wall time is the point here, so the bound
    # is generous (13x the deadline) and still far below the drip.
    assert time.monotonic() - started < 8.0


async def test_endless_chunked_body_without_content_length_is_capped(
    serve: Callable[[Handler], Awaitable[str]],
) -> None:
    block = b"10000\r\n" + b" " * 0x10000 + b"\r\n"

    async def endless(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        for _i in range(MAX_RESPONSE_BYTES // 0x10000 + 20):
            writer.write(block)
            await writer.drain()

    adapter = HttpTargetAdapter(
        HttpTargetConfig(type="http", url=await serve(endless), timeout_s=10)
    )
    with pytest.raises(TargetError, match="too large") as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert excinfo.value.transient is False


async def test_connection_reset_is_transient(
    serve: Callable[[Handler], Awaitable[str]],
) -> None:
    async def reset(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.transport.abort()

    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=await serve(reset), timeout_s=5))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert excinfo.value.transient is True
