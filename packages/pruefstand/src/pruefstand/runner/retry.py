"""Retry policy of target calls: transient errors and timeouts only, exponential backoff."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from pruefstand.core.errors import TargetError

MAX_ERROR_CHARS = 500
_JITTER = 0.25


@dataclass(frozen=True)
class Attempts[T]:
    """Outcome of ``call_with_retry``: a value or an error text, and the number of tries."""

    value: T | None
    error: str | None
    attempts: int


def backoff_delay(attempt: int, backoff_s: float, rng: np.random.Generator) -> float:
    """Return the wait before retry ``attempt`` (0-based): ``backoff_s * 2**attempt`` plus jitter.

    Args:
        attempt: 0 for the wait after the first failed try.
        backoff_s: Base delay in seconds.
        rng: Seeded generator; the jitter adds 0 to 25 % of the delay.

    Returns:
        Seconds to sleep.

    Examples:
        >>> import numpy as np
        >>> 2.0 <= backoff_delay(1, 1.0, np.random.default_rng(0)) < 2.5
        True
    """
    return backoff_s * 2.0**attempt * (1.0 + _JITTER * float(rng.random()))


def _clip(text: str) -> str:
    return text[:MAX_ERROR_CHARS]


async def call_with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
    rng: np.random.Generator,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Attempts[T]:
    """Run ``call`` with a per-try timeout; retry timeouts and ``TargetError(transient=True)``.

    There are at most ``max_retries + 1`` tries. A non-transient ``TargetError`` ends at once.
    Other exceptions (bugs) propagate; so does cancellation.

    Args:
        call: Zero-argument factory of the awaitable (called again for every try).
        timeout_s: Per-try deadline in seconds.
        max_retries: Extra tries after the first one.
        backoff_s: Base of the exponential wait between tries.
        rng: Seeded generator for the jitter.
        sleep: Wait function (replaceable in tests).

    Returns:
        ``Attempts`` with the value, or with an error text of at most 500 characters.
    """
    attempt = 0
    while True:
        try:
            value = await asyncio.wait_for(call(), timeout_s)
        except TimeoutError:
            error, transient = f"timeout after {timeout_s:g} s", True
        except TargetError as exc:
            error, transient = _clip(str(exc) or type(exc).__name__), exc.transient
        else:
            return Attempts(value, None, attempt + 1)
        if not transient or attempt >= max_retries:
            return Attempts(None, error, attempt + 1)
        await sleep(backoff_delay(attempt, backoff_s, rng))
        attempt += 1
