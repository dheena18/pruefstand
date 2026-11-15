import asyncio

import numpy as np
import pytest

from pruefstand.core.errors import TargetError
from pruefstand.runner.retry import backoff_delay, call_with_retry


class Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def rng() -> np.random.Generator:
    return np.random.default_rng(11)


def test_backoff_doubles_and_jitter_is_bounded_and_seeded() -> None:
    delays = [backoff_delay(k, 2.0, np.random.default_rng(5)) for k in range(4)]
    for k, delay in enumerate(delays):
        assert 2.0 * 2**k <= delay < 2.0 * 2**k * 1.25
    assert delays == [backoff_delay(k, 2.0, np.random.default_rng(5)) for k in range(4)]
    assert backoff_delay(3, 0.0, rng()) == 0.0


async def test_transient_errors_are_retried_until_success() -> None:
    calls = 0
    sleeper = Sleeper()

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            msg = "503 Service Unavailable"
            raise TargetError(msg, transient=True)
        return "ok"

    result = await call_with_retry(
        call, timeout_s=1, max_retries=3, backoff_s=0.5, rng=rng(), sleep=sleeper
    )
    assert (result.value, result.error, result.attempts) == ("ok", None, 3)
    assert len(sleeper.delays) == 2
    assert 0.5 <= sleeper.delays[0] < 0.5 * 1.25
    assert 1.0 <= sleeper.delays[1] < 1.0 * 1.25


async def test_non_transient_error_is_not_retried() -> None:
    sleeper = Sleeper()
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        msg = "400 bad request"
        raise TargetError(msg, transient=False)

    result = await call_with_retry(
        call, timeout_s=1, max_retries=3, backoff_s=0.5, rng=rng(), sleep=sleeper
    )
    assert calls == 1
    assert result.value is None
    assert result.attempts == 1
    assert result.error is not None
    assert "400 bad request" in result.error
    assert sleeper.delays == []


async def test_a_timeout_is_not_retried() -> None:
    # D624: the A40 generator serialises requests; retrying a read timeout only adds queue load
    sleeper = Sleeper()

    async def call() -> str:
        await asyncio.sleep(10)
        return "late"

    result = await call_with_retry(
        call, timeout_s=0.01, max_retries=3, backoff_s=0.0, rng=rng(), sleep=sleeper
    )
    assert result.attempts == 1
    assert sleeper.delays == []
    assert result.value is None
    assert result.error is not None
    assert "timeout" in result.error.lower()


async def test_no_retries_when_max_retries_is_zero() -> None:
    async def call() -> str:
        msg = "boom"
        raise TargetError(msg, transient=True)

    result = await call_with_retry(
        call, timeout_s=1, max_retries=0, backoff_s=0.0, rng=rng(), sleep=Sleeper()
    )
    assert result.attempts == 1
    assert result.error is not None


async def test_error_text_is_capped_at_500_characters() -> None:
    async def call() -> str:
        raise TargetError("x" * 5000, transient=False)

    result = await call_with_retry(
        call, timeout_s=1, max_retries=0, backoff_s=0.0, rng=rng(), sleep=Sleeper()
    )
    assert result.error is not None
    assert len(result.error) <= 500


async def test_unexpected_exceptions_are_not_swallowed() -> None:
    async def call() -> str:
        msg = "a bug"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="a bug"):
        await call_with_retry(
            call, timeout_s=1, max_retries=2, backoff_s=0.0, rng=rng(), sleep=Sleeper()
        )
