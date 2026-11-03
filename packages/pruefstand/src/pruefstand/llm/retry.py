"""Retry policy for model calls: exponential backoff with jitter, ``Retry-After``, quota rule."""

import asyncio
from dataclasses import dataclass

import numpy as np

from pruefstand.core.errors import LLMError


@dataclass(frozen=True)
class RetryPolicy:
    """How ``LLMClient`` retries transient failures (429, 5xx, timeout, connection loss).

    Attributes:
        max_retries: Retries after the first attempt.
        base_s: First backoff; doubles per attempt.
        cap_s: Upper bound of the exponential part.
        jitter: Fraction of the delay added at random (0 = none).
        max_retry_after_s: A ``Retry-After`` above this is a daily/hourly limit, not a pause:
            the client does not wait (an external provider is then marked exhausted).
        seed: Seed of the jitter generator (no global random state).
    """

    max_retries: int = 3
    base_s: float = 1.0
    cap_s: float = 30.0
    jitter: float = 0.25
    max_retry_after_s: float = 60.0
    seed: int = 0


class RateLimitedError(LLMError):
    """A 429 answer; carries the provider's ``Retry-After`` in seconds when it sent one."""

    def __init__(self, message: str, *, retry_after_s: float | None, status: int = 429) -> None:
        super().__init__(message, transient=True, status=status)
        self.retry_after_s = retry_after_s


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header given in seconds; dates and junk give None.

    Examples:
        >>> parse_retry_after("2"), parse_retry_after("0.5"), parse_retry_after("soon")
        (2.0, 0.5, None)
    """
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def backoff_delay(
    policy: RetryPolicy, attempt: int, retry_after_s: float | None, rng: np.random.Generator
) -> float:
    """Return the seconds to wait before retry number ``attempt + 1``.

    The larger of the provider's ``Retry-After`` and the exponential backoff, plus jitter.

    Examples:
        >>> p = RetryPolicy(base_s=1.0, cap_s=8.0, jitter=0.0)
        >>> [backoff_delay(p, n, None, np.random.default_rng(0)) for n in range(5)]
        [1.0, 2.0, 4.0, 8.0, 8.0]
        >>> backoff_delay(p, 0, 5.0, np.random.default_rng(0))
        5.0
    """
    delay = float(max(retry_after_s or 0.0, min(policy.cap_s, policy.base_s * 2**attempt)))
    return delay * (1.0 + policy.jitter * float(rng.random()))


async def pause(seconds: float) -> None:
    """Sleep; a module-level function so tests can replace it."""
    await asyncio.sleep(seconds)
