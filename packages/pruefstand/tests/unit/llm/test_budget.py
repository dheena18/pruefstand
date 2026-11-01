import asyncio

import pytest

from pruefstand.core.errors import BudgetExceeded
from pruefstand.core.models.llm import LLMResponse
from pruefstand.core.models.target import Usage
from pruefstand.llm.budget import Budget


def _resp(cost: float = 0.0, tokens: int = 10) -> LLMResponse:
    return LLMResponse(
        text="x",
        model="m",
        usage=Usage(prompt_tokens=tokens // 2, completion_tokens=tokens - tokens // 2),
        cost_usd=cost,
        latency_ms=1.0,
        cached=False,
    )


def test_usd_limit_raises_on_second_charge() -> None:
    budget = Budget(max_usd=1.0, max_tokens=None)
    budget.charge(_resp(cost=0.6))
    with pytest.raises(BudgetExceeded):
        budget.charge(_resp(cost=0.5))


def test_token_limit_raises_on_second_charge() -> None:
    budget = Budget(max_usd=None, max_tokens=100)
    budget.charge(_resp(tokens=60))
    with pytest.raises(BudgetExceeded):
        budget.charge(_resp(tokens=60))


def test_unreserved_request_cap_raises_on_third_charge() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=2)
    budget.charge(_resp())
    budget.charge(_resp())
    with pytest.raises(BudgetExceeded):
        budget.charge(_resp())


def test_requests_remaining_counts_down() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=2)
    assert budget.requests_remaining == 2
    budget.charge(_resp())
    assert budget.requests_remaining == 1
    budget.charge(_resp())
    assert budget.requests_remaining == 0


def test_requests_remaining_none_without_cap() -> None:
    assert Budget(max_usd=None, max_tokens=None).requests_remaining is None


def test_no_limits_never_raises() -> None:
    budget = Budget(max_usd=None, max_tokens=None)
    for _ in range(1000):
        budget.charge(_resp(cost=5.0, tokens=10_000))


async def test_reserve_until_cap_then_refuse() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=4)
    assert await budget.reserve(2) is True
    assert await budget.reserve(2) is True
    assert await budget.reserve(1) is False
    assert budget.requests_remaining == 0


async def test_charge_under_reservation_never_raises_for_cap() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=4)
    for _ in range(2):
        assert await budget.reserve(2) is True
        budget.charge(_resp())
        await budget.release(1)
    assert budget.requests_remaining == 2


async def test_release_then_reserve_again() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=2)
    assert await budget.reserve(2) is True
    assert await budget.reserve(1) is False
    await budget.release(1)
    assert await budget.reserve(1) is True


async def test_release_more_than_reserved_raises() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=4)
    await budget.reserve(4)
    with pytest.raises(ValueError, match="release"):
        await budget.release(5)


async def test_reserve_without_cap_is_always_true() -> None:
    assert await Budget(max_usd=None, max_tokens=None).reserve(100) is True


async def test_fifty_concurrent_reservations_respect_the_cap() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=10)
    granted = 0

    async def worker() -> None:
        nonlocal granted
        if await budget.reserve(2):
            granted += 1
            await asyncio.sleep(0)  # the model call
            budget.charge(_resp())
            await budget.release(1)

    await asyncio.gather(*(worker() for _ in range(50)))
    assert granted == 5
    assert budget.requests_remaining == 10 - 5


async def test_negative_reservations_are_refused() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=4)
    with pytest.raises(ValueError, match="negative"):
        await budget.reserve(-1)
    with pytest.raises(ValueError, match="negative"):
        await budget.release(-1)
    assert budget.requests_remaining == 4


def test_check_raises_once_a_limit_is_passed_and_not_before() -> None:
    budget = Budget(max_usd=None, max_tokens=10)
    budget.check()
    with pytest.raises(BudgetExceeded):
        budget.charge(_resp(tokens=20))
    with pytest.raises(BudgetExceeded):
        budget.check()


def test_check_stops_at_the_request_cap() -> None:
    budget = Budget(max_usd=None, max_tokens=None, max_requests=1)
    budget.check()
    budget.charge(_resp())
    with pytest.raises(BudgetExceeded):
        budget.check()
