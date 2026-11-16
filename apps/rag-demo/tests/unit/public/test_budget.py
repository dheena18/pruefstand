"""T8.4: the daily token and request budget (reserve, then settle)."""

from concurrent.futures import ThreadPoolExecutor

from rag_demo.public.budget import DailyBudget


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_reaching_the_token_cap_is_budget_exhausted_until_midnight_utc() -> None:
    clock = Clock(86400 * 30 + 3600.0)  # 01:00 UTC
    budget = DailyBudget(tokens=1000, clock=clock)
    assert budget.reserve(600) is None
    refused = budget.reserve(600)
    assert refused is not None
    assert (refused.code, refused.status) == ("budget_exhausted", 503)
    assert refused.retry_after_s == 86400 - 3600


def test_ten_concurrent_reserves_admit_at_most_five() -> None:
    budget = DailyBudget(tokens=3000)
    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(lambda _: budget.reserve(512), range(10)))
    assert sum(r is None for r in results) == 5  # 5 x 512 = 2560, a sixth would be 3072


def test_settle_refunds_the_unused_reserve() -> None:
    budget = DailyBudget(tokens=1000)
    assert budget.reserve(800) is None
    assert budget.reserve(800) is not None
    budget.settle(800, 100)  # only 100 tokens were generated
    assert budget.reserve(800) is None


def test_settle_never_charges_more_than_the_reservation() -> None:
    budget = DailyBudget(tokens=1000)
    assert budget.reserve(500) is None
    budget.settle(500, 9999)
    assert budget.reserve(500) is None
    assert budget.reserve(1) is not None


def test_the_request_cap_is_budget_exhausted() -> None:
    budget = DailyBudget(requests=2)
    assert budget.reserve(1) is None
    assert budget.reserve(1) is None
    refused = budget.reserve(1)
    assert refused is not None
    assert refused.code == "budget_exhausted"


def test_a_new_utc_day_starts_with_a_full_budget() -> None:
    clock = Clock(86400 * 30 + 10.0)
    budget = DailyBudget(tokens=100, clock=clock)
    assert budget.reserve(100) is None
    assert budget.reserve(1) is not None
    clock.now += 86400
    assert budget.reserve(100) is None


def test_reset_gives_back_a_full_budget() -> None:
    budget = DailyBudget(tokens=100)
    assert budget.reserve(100) is None
    budget.reset()
    assert budget.reserve(100) is None
