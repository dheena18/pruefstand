"""Pure ASGI body-size limit: 413 for a body over the cap, with or without ``Content-Length``."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BODY = b'{"detail":"request body too large"}'


class BodyLimitMiddleware:
    """Reject request bodies over ``max_bytes`` with 413 before any validator sees them.

    A ``Content-Length`` over the cap is refused up front. A body without that header (chunked
    transfer) or with a lying one is counted byte by byte in ``receive``: once the cap is passed
    the 413 is sent, the application sees a disconnect and everything it sends afterwards is
    dropped (FastAPI would turn the aborted read into its own 400).
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        """Wrap ``app``; ``max_bytes`` is the largest accepted request body."""
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the app, answering 413 for an oversized body."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"0")
        if declared.isdigit() and int(declared) > self._max:
            await self._reject(send)
            return
        seen = 0
        state = {"started": False, "rejected": False}

        async def counting_receive() -> Message:
            nonlocal seen
            if state["rejected"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self._max and not state["started"]:
                    state["rejected"] = True
                    await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if state["rejected"]:
                return
            state["started"] = state["started"] or message["type"] == "http.response.start"
            await send(message)

        await self._app(scope, counting_receive, guarded_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_BODY)).encode()),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": _BODY})
