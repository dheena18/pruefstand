"""``perturbation_consistency``: does a perturbed question get the same answer as its base?"""

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike
from pruefstand.judges.output import make_task
from pruefstand.metrics.judged.base import JudgedBase
from pruefstand.metrics.judged.truncate import over_cap


class BaseAnswers:
    """The answers of the unperturbed cases of one run, awaited by their perturbed variants.

    The runner creates one per run (``base_answers``), resolves each base case right after its
    target call (``None`` when it has no answer) and starts base cases before their variants, so
    a variant never waits for a case that cannot start.
    """

    def __init__(self, base_ids: Iterable[str]) -> None:
        self._futures: dict[str, asyncio.Future[str | None]] = {}
        loop = asyncio.get_running_loop()
        for base_id in base_ids:
            self._futures[base_id] = loop.create_future()

    def resolve(self, case_id: str, answer: str | None) -> None:
        """Record the answer of base case ``case_id``; an empty answer counts as missing."""
        future = self._futures.get(case_id)
        if future is not None and not future.done():
            future.set_result(answer if answer else None)

    async def get(self, case_id: str) -> str | None:
        """Return the base answer, waiting until it is known; None if missing or not in the run."""
        future = self._futures.get(case_id)
        return None if future is None else await future


_CURRENT: ContextVar[BaseAnswers | None] = ContextVar("base_answers", default=None)


@contextmanager
def base_answers(base_ids: Iterable[str]) -> Iterator[BaseAnswers]:
    """Make a ``BaseAnswers`` current for the tasks started inside the ``with`` block."""
    store = BaseAnswers(base_ids)
    token = _CURRENT.set(store)
    try:
        yield store
    finally:
        _CURRENT.reset(token)


class PerturbationConsistency(JudgedBase):
    """Same answer as the base case (raw 0 / 1, scored 0 / 1); ``referenz`` = the base answer."""

    name = "perturbation_consistency"

    def applicable(self, case: TestCase) -> bool:
        """Only perturbed cases."""
        return case.perturbation is not None

    async def acompute(
        self, case: TestCase, resp: TargetResponse, judges: JudgePoolLike
    ) -> MetricValue:
        """Judge ``resp.answer`` against the answer to the unperturbed question.

        Returns:
            ``not_applicable`` for an unperturbed case, without a base answer in this run, or
            when the input is over the judge's cap; otherwise the score.

        Raises:
            LLMError: The judge failed (the runner turns it into an error value).
            BudgetExceeded: The call passed a budget limit.
        """
        if case.perturbation is None:
            return self.na("not_perturbed")
        store = _CURRENT.get()
        base = None if store is None else await store.get(str(case.base_id))
        if base is None:
            return self.na("base_answer_missing")
        task = make_task(self.name, frage=case.question, referenz=base, antwort=resp.answer)
        if over_cap(judges.for_metric(self.name), task):
            return self.na("judge_input_too_long")
        return self.ok(await self.ask(judges, task))
