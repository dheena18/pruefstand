import asyncio

import pytest
from testsupport.runner_support import charge_one

from pruefstand.core.errors import BudgetExceeded
from pruefstand.core.models.llm import LLMResponse
from pruefstand.core.models.target import Usage
from pruefstand.llm.budget import Budget, tally_charges


def response(cost: float, prompt: int, completion: int) -> LLMResponse:
    return LLMResponse(
        text="{}",
        model="ollama/gemma3:12b",
        usage=Usage(prompt_tokens=prompt, completion_tokens=completion),
        cost_usd=cost,
        latency_ms=1.0,
        cached=False,
    )


def test_tally_counts_the_charges_made_inside_the_scope() -> None:
    budget = Budget(max_usd=None, max_tokens=None)
    budget.charge(response(0.5, 1, 1))  # before the scope: not counted
    with tally_charges() as tally:
        budget.charge(response(0.25, 100, 20))
        budget.charge(response(0.25, 10, 2))
    budget.charge(response(1.0, 1, 1))  # after the scope: not counted
    assert (tally.requests, tally.usd, tally.prompt_tokens, tally.completion_tokens) == (
        2,
        0.5,
        110,
        22,
    )


def test_nested_scopes_each_see_their_own_and_inner_charges() -> None:
    budget = Budget(max_usd=None, max_tokens=None)
    with tally_charges() as outer:
        charge_one(budget)
        with tally_charges() as inner:
            charge_one(budget)
        charge_one(budget)
    assert (outer.requests, inner.requests) == (3, 1)


async def test_concurrent_tasks_do_not_see_each_others_charges() -> None:
    budget = Budget(max_usd=None, max_tokens=None)

    async def worker(n: int) -> int:
        with tally_charges() as tally:
            for _ in range(n):
                charge_one(budget)
                await asyncio.sleep(0)
        return tally.requests

    assert await asyncio.gather(worker(1), worker(3), worker(2)) == [1, 3, 2]


def test_a_failing_charge_is_still_tallied() -> None:
    budget = Budget(max_usd=0.0, max_tokens=None)
    with tally_charges() as tally:
        with pytest.raises(BudgetExceeded):
            budget.charge(response(1.0, 1, 1))
    assert tally.requests == 1
