"""The judge hook of the runner: reservations, failures, quota and the hard-fail rule (T1.8).

The runner is the single owner of judge-failure and quota accounting (R9 D9-07). A judged
metric is called as ``await m.acompute(case, resp, judges)`` behind ``Budget.reserve(2)``
(the call plus one possible ``complete_json`` repair) and ``Budget.release(2 - used)``, where
``used`` is the number of requests that call charged (``llm.budget.tally_charges``).
"""

from collections import Counter
from dataclasses import dataclass, field

from pruefstand.core.errors import ConfigError, LLMError, QuotaExhausted
from pruefstand.core.logging import get_logger
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.target import CaseRecord, TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgedMetric, JudgePoolLike
from pruefstand.llm.budget import Budget, tally_charges
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.runner.routing import Route
from pruefstand.runner.scoring import not_applicable, target_error

_log = get_logger(__name__)
_RESERVED_PER_CALL = 2


@dataclass
class JudgeOutcome:
    """Values of the judged metrics of one case, the counts they caused, and whether a judge ran."""

    values: dict[str, MetricValue]
    counts: Counter[str] = field(default_factory=Counter)
    attempted: bool = False


def judged_metrics(registry: MetricRegistry) -> list[JudgedMetric]:
    """Return the registry's judged metrics.

    Raises:
        ConfigError: A metric of kind ``judged`` has no ``acompute``.
    """
    found: list[JudgedMetric] = []
    for m in registry.all():
        if m.kind is not MetricKind.JUDGED:
            continue
        if not isinstance(m, JudgedMetric):
            msg = f"judged metric {m.name!r} has no acompute() and would vanish silently"
            raise ConfigError(msg)
        found.append(m)
    return found


class JudgeStage:
    """Per-run judge hook; it holds the quota flag, so build one per run.

    Args:
        metrics: Registry; its judged metrics are scored here.
        judges: The judge pool, or None (every judged value is then ``not_applicable``).
        budget: Shared run budget; reservations are taken here.
        hard_fail: Metric names whose value 1 keeps the case away from the judges.

    Raises:
        ConfigError: (constructor) a judged metric has no ``acompute``.
    """

    def __init__(
        self,
        metrics: MetricRegistry,
        judges: JudgePoolLike | None,
        budget: Budget,
        hard_fail: tuple[str, ...],
    ) -> None:
        self._metrics = judged_metrics(metrics)
        self._judges = judges
        self._budget = budget
        self._hard_fail = frozenset(hard_fail)
        self._quota_exhausted = False

    async def judge(
        self,
        case: TestCase,
        record: CaseRecord,
        route: Route,
        deterministic: dict[str, MetricValue],
        *,
        judged_subset: bool,
    ) -> JudgeOutcome:
        """Score every judged metric of one case.

        Args:
            case: The test case.
            record: Its exchange with the target.
            route: How the case was routed.
            deterministic: Its deterministic values (for the hard-fail rule).
            judged_subset: Whether the run limits judging to ``TestCase.judged_subset`` cases.

        Returns:
            One value per judged metric plus the counts they caused.

        Raises:
            BudgetExceeded: A judge call passed the USD or token cap (not caught here).
        """
        outcome = JudgeOutcome({})
        # fail closed: a hard-fail metric that fired (1) or could not be verified (error)
        hard = any(
            v.metric in self._hard_fail
            and (v.status is MetricStatus.ERROR or (v.status is MetricStatus.OK and v.value == 1.0))
            for v in deterministic.values()
        )
        resp, judges = record.response, self._judges
        for m in self._metrics:
            value = self._without_call(
                m, case, record, route, hard_failed=hard, judged_subset=judged_subset
            )
            if value is None and judges is not None and resp is not None:
                value = await self._call(m, case, resp, judges, outcome)
            outcome.values[m.name] = value if value is not None else target_error(m)
        return outcome

    def _without_call(
        self,
        m: JudgedMetric,
        case: TestCase,
        record: CaseRecord,
        route: Route,
        *,
        hard_failed: bool,
        judged_subset: bool,
    ) -> MetricValue | None:
        """Return the value of a metric that needs no judge call, or None when it needs one."""
        checks = (
            (m.applies_to is not None and case.category not in m.applies_to, "category"),
            (judged_subset and not case.judged_subset, "not_in_judged_subset"),
            (route.mode == "retrieve", "retrieve_mode"),
            (self._judges is None, "no_judges"),
        )
        for applies, reason in checks:
            if applies:
                return not_applicable(m, reason)
        if record.response is None:
            return target_error(m)
        return not_applicable(m, "hard_fail") if hard_failed else None

    async def _call(
        self,
        m: JudgedMetric,
        case: TestCase,
        resp: TargetResponse,
        judges: JudgePoolLike,
        outcome: JudgeOutcome,
    ) -> MetricValue:
        if self._quota_exhausted:
            return self._skipped(m, "judge_quota", outcome)
        if not await self._budget.reserve(_RESERVED_PER_CALL):
            return self._skipped(m, "judge_cap", outcome)
        with tally_charges() as tally:
            try:
                value = await m.acompute(case, resp, judges)
            except QuotaExhausted:
                self._quota_exhausted = True
                return self._skipped(m, "judge_quota", outcome)
            except LLMError as exc:  # incl. PolicyViolation; BudgetExceeded is not an LLMError
                outcome.counts["judge_error"] += 1
                outcome.attempted = True
                return MetricValue(
                    metric=m.name,
                    metric_version=m.version,
                    value=None,
                    status=MetricStatus.ERROR,
                    details={"error": type(exc).__name__},
                )
            finally:
                await self._release(tally.requests)
        outcome.attempted = True
        return value

    @staticmethod
    def _skipped(m: JudgedMetric, reason: str, outcome: JudgeOutcome) -> MetricValue:
        outcome.counts["judge_skipped"] += 1
        return not_applicable(m, reason)

    async def _release(self, used: int) -> None:
        try:
            await self._budget.release(max(0, _RESERVED_PER_CALL - used))
        except ValueError:
            _log.warning("judge_budget_release_mismatch", used=used)
