"""Retry policy for model calls: exponential backoff with jitter, ``Retry-After``, quota rule."""

import asyncio
from dataclasses import dataclass

import numpy as np

from pruefstand.core.errors import LLMError, QuotaExhausted
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.protocols import LLMBackend
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.recorder import CallRecorder

_EXCERPT = 200
HTTP_TOO_MANY_REQUESTS = 429


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


def describe(err: Exception) -> str:
    """Return ``Type: message`` cut to a recorder-friendly length."""
    return f"{type(err).__name__}: {err}"[: _EXCERPT * 2]


class Retrier:
    """Runs one logical backend call with retries; records every failed attempt.

    Args:
        policy: Backoff policy.
        recorder: Receives one row per failed attempt.
    """

    def __init__(self, policy: RetryPolicy, recorder: CallRecorder) -> None:
        self._policy = policy
        self._recorder = recorder
        self._rng = np.random.default_rng(policy.seed)

    async def call(self, backend: LLMBackend, req: LLMRequest) -> LLMResponse:
        """Call ``backend`` until it answers, fails permanently or the retries are used up.

        Raises:
            QuotaExhausted: An external provider's 429 survived the retries, or its
                ``Retry-After`` exceeds the wait cap.
            LLMError: Permanent failure, or a transient one after the last retry (a local
                provider's ``Retry-After`` above the cap also ends the retries at once).
        """
        for attempt in range(self._policy.max_retries + 1):
            try:
                return await backend.acomplete(req)
            except LLMError as err:
                await self._after_failure(req, err, attempt)  # raises unless a retry follows
            except Exception as err:
                self._recorder.record(req, None, type(err).__name__)  # message may hold secrets
                msg = f"backend failed: {type(err).__name__}"
                raise LLMError(msg, transient=False) from err
        msg = "retry loop ended without an answer"  # unreachable: the last attempt raises
        raise LLMError(msg, transient=False)

    async def _after_failure(self, req: LLMRequest, err: LLMError, attempt: int) -> None:
        policy = self._policy
        wait = err.retry_after_s if isinstance(err, RateLimitedError) else None
        final = attempt >= policy.max_retries
        too_long = wait is not None and wait > policy.max_retry_after_s
        external_429 = err.status == HTTP_TOO_MANY_REQUESTS and (
            provider_of(req.model) not in LOCAL_PROVIDERS
        )
        if external_429 and (final or too_long):
            self._recorder.record(req, None, describe(err))
            msg = f"{req.model}: free quota exhausted ({describe(err)})"
            raise QuotaExhausted(msg, status=HTTP_TOO_MANY_REQUESTS) from err
        if not external_429 and (not err.transient or final or too_long):
            self._recorder.record(req, None, describe(err))
            raise err
        self._recorder.record(req, None, f"retry {attempt + 1}: {describe(err)}")
        await pause(backoff_delay(policy, attempt, wait, self._rng))
