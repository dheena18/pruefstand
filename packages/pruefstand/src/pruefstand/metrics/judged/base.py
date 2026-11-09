"""Common base of the judged metrics (T5.2b): applicability, empty values, one judge call."""

from pruefstand.core.enums import Category
from pruefstand.core.models.judge import JudgeTask, JudgeVerdict
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike

Details = dict[str, str | float | int | bool]
ANSWERABLE = frozenset(
    {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
)


class JudgedBase:
    """Template of a metric scored by a judge (``version = "1"``, higher is better).

    Subclasses set ``name`` (a key of ``judges.output.SPECS``), ``requires`` and ``applies_to`` and
    implement ``applicable`` (what is known before the target answered, used for the tier-1
    selection) and ``acompute``. A judge failure is **not** caught here: ``LLMError`` and
    ``BudgetExceeded`` propagate to the runner, which owns the error value, the counts and the
    degraded flag (R9 D9-07). Only the normalised score and the raw score are kept in the value,
    never the judge's ``reason`` (it can echo canary or private text).
    """

    name: str
    version: str = "1"
    kind: MetricKind = MetricKind.JUDGED
    higher_is_better: bool = True
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    def applicable(self, case: TestCase) -> bool:
        """Whether the metric can apply to ``case`` before any answer exists."""
        return self.applies_to is None or case.category in self.applies_to

    def ok(self, verdict: JudgeVerdict, **details: str | float | int | bool) -> MetricValue:
        """Return the ``ok`` value of a verdict: its normalised score and raw score."""
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=verdict.score,
            status=MetricStatus.OK,
            details={"raw_score": verdict.raw_score, **details},
        )

    def na(self, reason: str, **details: str | float | int | bool) -> MetricValue:
        """Return a ``not_applicable`` value carrying the reason (never a 0)."""
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            details={"reason": reason, **details},
        )

    async def ask(self, judges: JudgePoolLike, task: JudgeTask) -> JudgeVerdict:
        """Send ``task`` to the judge of this metric.

        Raises:
            LLMError: The judge failed (incl. ``PolicyViolation``, ``QuotaExhausted``).
            BudgetExceeded: The call passed a budget limit.
        """
        return await judges.for_metric(self.name).score(task)
