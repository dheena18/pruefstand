"""``answer_correctness``: does the answer state what the reference answer states?"""

from pruefstand.core.enums import Category
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike
from pruefstand.judges.output import make_task
from pruefstand.metrics.judged.base import ANSWERABLE, JudgedBase
from pruefstand.metrics.judged.truncate import over_cap


class AnswerCorrectness(JudgedBase):
    """Correctness against ``reference_answer`` (raw 0 / 1 / 2, scored 0 / 0.5 / 1)."""

    name = "answer_correctness"
    applies_to: frozenset[Category] | None = ANSWERABLE

    def applicable(self, case: TestCase) -> bool:
        """Answerable categories with a reference answer."""
        return super().applicable(case) and case.reference_answer is not None

    async def acompute(
        self, case: TestCase, resp: TargetResponse, judges: JudgePoolLike
    ) -> MetricValue:
        """Judge ``resp.answer`` against ``case.reference_answer``.

        Returns:
            ``not_applicable`` without a reference answer or when the input is over the judge's
            cap (question, answer and reference are never cut); otherwise the score.

        Raises:
            LLMError: The judge failed (the runner turns it into an error value).
            BudgetExceeded: The call passed a budget limit.
        """
        if case.reference_answer is None:
            return self.na("no_reference")
        task = make_task(
            self.name, frage=case.question, referenz=case.reference_answer, antwort=resp.answer
        )
        if over_cap(judges.for_metric(self.name), task):
            return self.na("judge_input_too_long")
        return self.ok(await self.ask(judges, task))
