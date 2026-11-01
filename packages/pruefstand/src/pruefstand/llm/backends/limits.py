"""Bounded HTTP responses for model calls: a byte cap on the body, an answer-length cap."""

from collections.abc import AsyncIterator

import httpx

_CHARS_PER_TOKEN_CAP = 16
_TEXT_SLACK = 4096
_JSON_ESCAPE_FACTOR = 6  # a character is at most 6 bytes of JSON (\\uXXXX)
_BYTES_SLACK = 16384


def response_limits(max_tokens: int) -> tuple[int, int]:
    """Return ``(max answer characters, max response bytes)`` allowed for ``max_tokens``.

    Examples:
        >>> response_limits(16)[0]
        4352
    """
    chars = max_tokens * _CHARS_PER_TOKEN_CAP + _TEXT_SLACK
    return chars, chars * _JSON_ESCAPE_FACTOR + _BYTES_SLACK


class _TooLargeError(Exception):
    """The response body passed its byte limit."""


class _LimitedStream(httpx.AsyncByteStream):
    """Response body that stops at ``limit`` bytes and remembers that it did."""

    def __init__(self, inner: httpx.AsyncByteStream, limit: int, tripped: list[bool]) -> None:
        self._inner = inner
        self._limit = limit
        self._tripped = tripped

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._inner:
            total += len(chunk)
            if total > self._limit:
                self._tripped.append(True)
                raise _TooLargeError
            yield chunk

    async def aclose(self) -> None:
        """Close the wrapped stream."""
        await self._inner.aclose()


class LimitedTransport(httpx.AsyncBaseTransport):
    """``httpx`` transport that bounds the size of every response body."""

    def __init__(self, limit: int, tripped: list[bool]) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._limit = limit
        self._tripped = tripped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request; a declared or actual body over the limit raises and trips the flag."""
        resp = await self._inner.handle_async_request(request)
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._limit:
            self._tripped.append(True)
            await resp.aclose()
            raise _TooLargeError
        assert isinstance(resp.stream, httpx.AsyncByteStream)  # noqa: S101  (httpx contract)
        return httpx.Response(
            status_code=resp.status_code,
            headers=resp.headers,
            stream=_LimitedStream(resp.stream, self._limit, self._tripped),
            extensions=resp.extensions,
        )

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._inner.aclose()

IDENTITY_HEADERS = {"Accept-Encoding": "identity"}
