"""HTTP adapter for Target API v1 (interfaces §1.1, §4).

The target is untrusted: it may answer with huge, malformed, slow, redirecting or hostile
responses. Every call therefore has connect/read timeouts plus a total deadline, a response
size cap, no redirects, and only ``http``/``https`` base URLs. The bearer token is read from
the environment variable named by ``auth_env`` at call time and never appears in logs,
exceptions or the body excerpts of error messages. There are no retries here (runner, T1.8).
"""

import asyncio
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import ConfigError, TargetError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.target import (
    RetrievedChunk,
    RetrieveResponse,
    TargetInfo,
    TargetRequest,
    TargetResponse,
)
from pruefstand.core.protocols import TargetAdapter

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
"""Hard cap on one response body (raw bytes, no content-encoding accepted)."""

_CONNECT_TIMEOUT_S = 10.0
_EXCERPT_CHARS = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_REDACTED = "[REDACTED]"
_NO_RETRIEVE = frozenset({404, 405})

_log = get_logger(__name__)


def _reject_constant(name: str) -> object:
    msg = f"non-finite number {name} is not valid JSON"
    raise ValueError(msg)


def _validated_base(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        msg = "target url must be an http:// or https:// URL with a host"
        raise ConfigError(msg)
    if parts.username is not None or parts.password is not None:
        msg = "target url must not contain credentials; use auth_env"
        raise ConfigError(msg)
    if parts.query or parts.fragment:
        msg = "target url must not contain a query or fragment"
        raise ConfigError(msg)
    return url.rstrip("/")


class HttpTargetAdapter(TargetAdapter):
    """Client of a system under test that speaks Target API v1 over HTTP.

    Args:
        cfg: Target configuration (``url``, ``auth_env``, ``timeout_s``).

    Raises:
        ConfigError: ``cfg.url`` is not a plain http(s) URL (credentials, query or fragment
            in the URL are refused as well).
    """

    def __init__(self, cfg: HttpTargetConfig) -> None:
        self._base = _validated_base(cfg.url)
        self._auth_env = cfg.auth_env
        self._timeout_s = cfg.timeout_s
        self._closed = False
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.timeout_s, connect=min(cfg.timeout_s, _CONNECT_TIMEOUT_S)),
            follow_redirects=False,
            trust_env=False,  # no ~/.netrc credentials, no proxy env vars for an untrusted target
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )

    async def info(self) -> TargetInfo | None:
        """Return ``GET /v1/info``.

        Returns:
            The parsed info, or ``None`` when the target answers 404 (opaque target).

        Raises:
            TargetError: Transport error, other HTTP error, or an invalid response.
        """
        what = "GET /v1/info"
        status, data = await self._call("GET", "/v1/info", None)
        if status == 404:  # HTTP "not found" means an opaque target
            return None
        return _parse(TargetInfo, self._checked(what, status, data), what, self._secret())

    async def query(self, req: TargetRequest) -> TargetResponse:
        """Return ``POST /v1/query`` for ``req``.

        The wire ``request_id`` is always a fresh ``uuid4().hex``; whatever ``req.request_id``
        holds (a runner may park a test label there) is never sent.

        Raises:
            TargetError: ``transient=True`` for timeouts, connection errors and 5xx;
                ``transient=False`` for 4xx, redirects, oversized or invalid responses.
        """
        what = "POST /v1/query"
        status, data = await self._call("POST", "/v1/query", req)
        response = _parse(TargetResponse, self._checked(what, status, data), what, self._secret())
        _check_finite(response.chunks, what)
        return response

    async def retrieve(self, req: TargetRequest) -> RetrieveResponse | None:
        """Return ``POST /v1/retrieve`` (retrieval only, R11 D218).

        Returns:
            The chunks in rank order, or ``None`` when the target has no such endpoint
            (HTTP 404 or 405).

        Raises:
            TargetError: As for ``query``; a response that contains an ``answer`` key is a
                permanent error (a retrieve endpoint must not generate).
        """
        what = "POST /v1/retrieve"
        status, data = await self._call("POST", "/v1/retrieve", req)
        if status in _NO_RETRIEVE:
            return None
        body = _load_json(self._checked(what, status, data), what, self._secret())
        if isinstance(body, dict) and "answer" in body:
            msg = f"{what}: response contains an 'answer'; a retrieve endpoint must not generate"
            raise TargetError(msg, transient=False)
        response = _validate(RetrieveResponse, body, what)
        _check_finite(response.chunks, what)
        return response

    async def aclose(self) -> None:
        """Close the connection pool; safe to call more than once."""
        self._closed = True
        await self._client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        if self._auth_env is None:
            return {}
        token = os.environ.get(self._auth_env, "")
        if not token:
            msg = f"auth env var {self._auth_env} is not set or empty"
            raise TargetError(msg, transient=False)
        if not (token.isascii() and token.isprintable()):
            msg = f"auth env var {self._auth_env} does not hold a printable ASCII token"
            raise TargetError(msg, transient=False)
        return {"Authorization": f"Bearer {token}"}

    def _secret(self) -> str:
        return os.environ.get(self._auth_env, "") if self._auth_env else ""

    def _checked(self, what: str, status: int, data: bytes) -> bytes:
        """Return ``data`` for a 2xx status, else raise the matching ``TargetError``."""
        if 300 <= status < 400:
            msg = f"{what}: target answered HTTP {status}; redirects are not followed"
            raise TargetError(msg, transient=False)
        if not 200 <= status < 300:
            msg = f"{what}: HTTP {status}: {_excerpt(data, self._secret())}"
            raise TargetError(msg, transient=status >= 500)
        return data

    async def _call(self, method: str, path: str, req: TargetRequest | None) -> tuple[int, bytes]:
        """One bounded HTTP exchange; returns ``(status, body)`` of the final response."""
        if self._closed:
            msg = "adapter is closed"
            raise TargetError(msg, transient=False)
        what = f"{method} {path}"
        body = None if req is None else {**req.model_dump(mode="json"), "request_id": uuid4().hex}
        started = time.monotonic()
        try:
            async with asyncio.timeout(self._timeout_s):
                status, data = await self._exchange(method, path, body)
        except (TimeoutError, httpx.TimeoutException) as exc:
            msg = f"{what}: timed out after {self._timeout_s:g}s"
            raise TargetError(msg, transient=True) from exc
        except httpx.HTTPError as exc:
            msg = f"{what}: connection failed ({type(exc).__name__})"
            raise TargetError(msg, transient=True) from exc
        elapsed_ms = round(1000 * (time.monotonic() - started))
        _log.debug("target_call", what=what, status=status, elapsed_ms=elapsed_ms)
        return status, data

    async def _exchange(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> tuple[int, bytes]:
        headers = self._auth_headers()
        async with self._client.stream(
            method, self._base + path, json=body, headers=headers
        ) as response:
            what = f"{method} {path}"
            if 300 <= response.status_code < 400:
                return response.status_code, b""
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                msg = f"{what}: response too large (declared {declared} bytes)"
                raise TargetError(msg, transient=False)
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                msg = f"{what}: content-encoding is not accepted"
                raise TargetError(msg, transient=False)
            chunks: list[bytes] = []
            total = 0
            async for part in response.aiter_raw():
                total += len(part)
                if total > MAX_RESPONSE_BYTES:
                    msg = f"{what}: response too large (> {MAX_RESPONSE_BYTES} bytes)"
                    raise TargetError(msg, transient=False)
                chunks.append(part)
            return response.status_code, b"".join(chunks)


def _excerpt(data: bytes, secret: str) -> str:
    """First ``_EXCERPT_CHARS`` characters of an untrusted body, safe for messages."""
    text = data[: _EXCERPT_CHARS * 8].decode("utf-8", errors="replace")
    if secret:
        text = text.replace(secret, _REDACTED)
    return _CONTROL.sub(" ", text).strip()[:_EXCERPT_CHARS]


def _load_json(data: bytes, what: str, secret: str) -> object:
    try:
        body = json.loads(data, parse_constant=_reject_constant)
        json.dumps(body, ensure_ascii=False).encode("utf-8")  # rejects lone surrogates
    except (ValueError, RecursionError) as exc:
        msg = f"{what}: invalid JSON ({type(exc).__name__}): {_excerpt(data, secret)}"
        raise TargetError(msg, transient=False) from None
    return body


def _validate[M: BaseModel](model: type[M], body: object, what: str) -> M:
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False, include_context=False)[:3]
        )
        msg = f"{what}: response does not match Target API v1 ({problems})"
        raise TargetError(msg[:400], transient=False) from None


def _parse[M: BaseModel](model: type[M], data: bytes, what: str, secret: str) -> M:
    return _validate(model, _load_json(data, what, secret), what)


def _check_finite(chunks: tuple[RetrievedChunk, ...] | None, what: str) -> None:
    if chunks is not None and not all(math.isfinite(chunk.score) for chunk in chunks):
        msg = f"{what}: chunk score is not a finite number"
        raise TargetError(msg, transient=False)
