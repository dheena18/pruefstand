"""Cancel work when the HTTP client goes away (T3.6a, D624).

Starlette does not cancel a running handler when the client disconnects. For ``/v1/query`` that
leaves the upstream Ollama request queued: a runner that timed out would leave up to four
duplicate generations behind. ``cancel_on_disconnect`` races the work against the ASGI
``http.disconnect`` message and cancels the work (closing the upstream connection) when it wins.
"""

import asyncio
from collections.abc import Awaitable
from contextlib import suppress

from starlette.requests import Request

from rag_demo.errors import ClientDisconnectedError


async def _wait_for_disconnect(request: Request) -> None:
    """Return when the ASGI server reports ``http.disconnect`` (the body is already read)."""
    while (await request.receive())["type"] != "http.disconnect":
        continue


async def cancel_on_disconnect[T](request: Request, work: Awaitable[T]) -> T:
    """Await ``work``; cancel it and raise when the client disconnects first.

    Args:
        request: The request whose connection is watched; its body must be read already.
        work: The awaitable to run, e.g. the generator call.

    Returns:
        The result of ``work``.

    Raises:
        Exception: Whatever ``work`` or the ASGI ``receive`` of the request raises.
        ClientDisconnectedError: The client went away before ``work`` finished; ``work`` is
            cancelled (an httpx call closes its upstream connection).
    """
    task = asyncio.ensure_future(work)
    watcher = asyncio.create_task(_wait_for_disconnect(request))
    try:
        await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            return task.result()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        watcher.result()  # a failing receive() is an error, not a disconnect
        raise ClientDisconnectedError
    finally:
        if watcher.done() and not watcher.cancelled():
            watcher.exception()  # mark retrieved: no "exception was never retrieved"
        watcher.cancel()
        if not task.done():
            task.cancel()
