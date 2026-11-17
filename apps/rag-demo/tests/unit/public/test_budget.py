"""T8.4: the daily token and request budget (reserve, then settle)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from rag_demo.public.budget import DailyBudget, Reservation
from rag_demo.public.errors import Rejection


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_reaching_the_token_cap_is_budget_exhausted_until_midnight_utc() -> None:
    clock = Clock(86400 * 30 + 3600.0)  # 01:00 UTC
    budget = DailyBudget(tokens=1000, clock=clock)
    assert not isinstance(budget.reserve(600), Rejection)
    refused = budget.reserve(600)
    assert isinstance(refused, Rejection)
    assert (refused.code, refused.status) == ("budget_exhausted", 503)
    assert refused.retry_after_s == 86400 - 3600


class _SlowBudget(DailyBudget):
    """Reading the used tokens takes a moment: without the lock every thread sees a stale value."""

    _stored = 0

    @property
    def _used(self) -> int:
        time.sleep(0.003)
        return self._stored

    @_used.setter
    def _used(self, value: int) -> None:
        self._stored = value


def test_ten_concurrent_reserves_admit_at_most_five() -> None:
    budget = _SlowBudget(tokens=3000, clock=lambda: 86400 * 30 + 1.0)
    barrier = threading.Barrier(10)

    def go(_: int) -> Rejection | Reservation:
        barrier.wait()
        return budget.reserve(512)

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(go, range(10)))
    assert (
        sum(not isinstance(r, Rejection) for r in results) == 5
    )  # 5 x 512 = 2560; a sixth is 3072


def test_a_settle_across_midnight_leaves_the_new_days_reservations_alone() -> None:
    """Opus B1: a settle of yesterday's reservation must not erase today's."""
    clock = Clock(86400 * 30 + 86399.0)  # 23:59:59
    budget = DailyBudget(tokens=1000, clock=clock)
    a = budget.reserve(512)
    assert not isinstance(a, Rejection)
    clock.now += 2  # just after midnight: a new day
    b = budget.reserve(512)
    assert not isinstance(b, Rejection)
    budget.settle(a, 100)  # yesterday's generation ends: today's 512 stay reserved
    assert isinstance(budget.reserve(900), Rejection)  # 512 + 900 would be 1412 > 1000
    budget.settle(b, 100)
    assert not isinstance(budget.reserve(900), Rejection)


def test_settle_refunds_the_unused_reserve() -> None:
    budget = DailyBudget(tokens=1000)
    first = budget.reserve(800)
    assert not isinstance(first, Rejection)
    assert isinstance(budget.reserve(800), Rejection)
    budget.settle(first, 100)  # only 100 tokens were generated
    assert not isinstance(budget.reserve(800), Rejection)


def test_settle_never_charges_more_than_the_reservation() -> None:
    budget = DailyBudget(tokens=1000)
    ticket = budget.reserve(500)
    assert not isinstance(ticket, Rejection)
    budget.settle(ticket, 9999)
    assert not isinstance(budget.reserve(500), Rejection)
    assert isinstance(budget.reserve(1), Rejection)


def test_the_request_cap_is_budget_exhausted() -> None:
    budget = DailyBudget(requests=2)
    assert not isinstance(budget.reserve(1), Rejection)
    assert not isinstance(budget.reserve(1), Rejection)
    refused = budget.reserve(1)
    assert isinstance(refused, Rejection)
    assert refused.code == "budget_exhausted"


def test_a_new_utc_day_starts_with_a_full_budget() -> None:
    clock = Clock(86400 * 30 + 10.0)
    budget = DailyBudget(tokens=100, clock=clock)
    assert not isinstance(budget.reserve(100), Rejection)
    assert isinstance(budget.reserve(1), Rejection)
    clock.now += 86400
    assert not isinstance(budget.reserve(100), Rejection)


def test_reset_gives_back_a_full_budget() -> None:
    budget = DailyBudget(tokens=100)
    assert not isinstance(budget.reserve(100), Rejection)
    budget.reset()
    assert not isinstance(budget.reserve(100), Rejection)
