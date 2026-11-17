"""ASGI guard of the public demo (T8.4): kill switch, rate limit, validation, budget, timeout.

Wrapped around the app only when ``public_mode`` is on. For ``POST /v1/query`` (and the
kill switch and rate limit for ``/v1/retrieve``) it answers every refusal with the fixed
``{code, message, retry_after_s}`` body and never lets a question reach a log.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rag_demo.public.budget import DailyBudget
from rag_demo.public.errors import Rejection
from rag_demo.public.limits import Limiter, client_key

MAX_BODY = 8 * 1024
MAX_QUESTION = 500
_log = logging.getLogger(__name__)
GUARDED = frozenset({"/v1/query", "/v1/retrieve"})


@dataclass(frozen=True)
class GuardConfig:
    """What the guard needs of the configuration.

    Attributes:
        tenants: The fixed tenant allow-list.
        hops: ``TRUSTED_PROXY_HOPS``.
        max_tokens: The worst case reserved per generation.
        timeout_s: ``DEMO_TIMEOUT_S``.
        top_k: The fixed ``top_k`` (a client value is ignored).
    """

    tenants: frozenset[str]
    hops: int
    max_tokens: int
    timeout_s: float
    top_k: int


async def _send_rejection(send: Send, rejection: Rejection) -> None:
    body = json.dumps(rejection.body()).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += [(k.lower().encode(), v.encode()) for k, v in rejection.headers().items()]
    await send({"type": "http.response.start", "status": rejection.status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive: Receive) -> bytes | None:
    """The whole body, or ``None`` when it is over ``MAX_BODY``."""
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return b"".join(chunks)
        size += len(message.get("body", b""))
        if size > MAX_BODY:
            return None
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def checked_body(raw: bytes, cfg: GuardConfig, request_id: str) -> bytes | None:
    """Validate a query body and rewrite it server-side; ``None`` when it is not valid.

    The tenant must be on the allow-list, the question 1-500 characters; unknown fields are
    refused, a client ``request_id`` and ``top_k`` are replaced by the server's.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not set(data) <= {
        "tenant_id",
        "question",
        "top_k",
        "request_id",
    }:
        return None
    tenant, question = data.get("tenant_id"), data.get("question")
    if not isinstance(tenant, str) or not isinstance(question, str) or tenant not in cfg.tenants:
        return None
    if not 1 <= len(question) <= MAX_QUESTION:
        return None
    top_k, client_id = data.get("top_k"), data.get("request_id", "")
    if not (top_k is None or type(top_k) is int) or not isinstance(client_id, str):
        return None  # the values are replaced below, but a wrong type is still a bad request
    clean = {
        "tenant_id": data["tenant_id"],
        "question": question,
        "top_k": cfg.top_k,
        "request_id": request_id,
    }
    return json.dumps(clean).encode()


class PublicGuard:
    """Run the controls of the public demo in front of ``app``."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: Limiter,
        budget: DailyBudget,
        cfg: GuardConfig,
        disabled: Callable[[], bool],
        new_id: Callable[[], str],
    ) -> None:
        """Wrap ``app``; ``disabled`` is the kill switch, ``new_id`` makes server request ids."""
        self._app = app
        self._limiter = limiter
        self._budget = budget
        self._cfg = cfg
        self._disabled = disabled
        self._new_id = new_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer a refusal or pass the (rewritten) request on; a crash is a ``server_error``."""
        started = False

        async def watching(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._guarded(scope, receive, watching)
        except Exception:
            _log.exception("public guard failed")  # the traceback holds no question text
            if not started:
                await _send_rejection(send, Rejection("server_error"))

    async def _guarded(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in GUARDED or scope["method"] != "POST":
            await self._app(scope, receive, send)
            return
        if self._disabled():
            await _send_rejection(send, Rejection("demo_disabled"))
            return
        lines = [v.decode("latin-1") for k, v in scope["headers"] if k == b"x-forwarded-for"]
        forwarded = ", ".join(lines) or None  # every header line, in order (RFC 7230 combining)
        peer = scope["client"][0] if scope.get("client") else None
        refused = self._limiter.admit(client_key(peer, forwarded, self._cfg.hops))
        if refused is not None:
            await _send_rejection(send, refused)
            return
        if scope["path"] == "/v1/query":
            await self._query(scope, receive, send)
        else:
            await self._app(scope, receive, send)

    async def _query(self, scope: Scope, receive: Receive, send: Send) -> None:
        raw = await _read_body(receive)
        if raw is None:
            await _send_rejection(send, Rejection("body_too_large"))
            return
        body = checked_body(raw, self._cfg, self._new_id())
        if body is None:
            await _send_rejection(send, Rejection("invalid_request"))
            return
        busy = self._limiter.acquire()
        if busy is not None:
            await _send_rejection(send, busy)
            return
        reservation = self._budget.reserve(self._cfg.max_tokens)
        if isinstance(reservation, Rejection):
            self._limiter.release()
            await _send_rejection(send, reservation)
            return
        used = 0
        try:
            used = await self._run(scope, receive, body, send)
        finally:
            self._budget.settle(reservation, used)
            self._limiter.release()

    async def _run(self, scope: Scope, receive: Receive, body: bytes, send: Send) -> int:
        """Call the app with the checked body under the timeout; return the tokens generated."""
        sent = False
        captured: list[bytes] = []
        status = 0

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:  # later reads (disconnect watching) see the real connection
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def watching(message: Message) -> None:
            nonlocal sent, status
            sent = True
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "http.response.body":
                captured.append(message.get("body", b""))
            await send(message)

        try:
            async with asyncio.timeout(self._cfg.timeout_s):
                await self._app(scope, replay, watching)
        except TimeoutError:
            if not sent:
                await _send_rejection(send, Rejection("timeout"))
            return self._cfg.max_tokens  # the generator may have run to its limit
        return _completion_tokens(status, b"".join(captured))


def _completion_tokens(status: int, body: bytes) -> int:
    """Generated tokens from a 200 answer body; 0 for anything else."""
    if status != 200:
        return 0
    try:
        usage = json.loads(body).get("usage") or {}
        return max(0, int(usage.get("completion_tokens", 0)))
    except (ValueError, TypeError, AttributeError):
        return 0
