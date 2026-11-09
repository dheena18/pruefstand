"""Per-case value rules of the pairing: lookup, request failure, worst-fill and judge-side flags."""

from pruefstand.core.models.metric import JUDGE_SIDE_REASONS, MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults, ScoredCase


def lookup(scored: ScoredCase, metric: str) -> MetricValue | None:
    for value in scored.values:
        if value.metric == metric:
            return value
    return None


def request_failed(scored: ScoredCase) -> bool:
    value = lookup(scored, "error_rate")
    return value is not None and value.value is not None and value.value >= 1.0


def fillable(scored: ScoredCase, value: MetricValue | None, *, fill_errors: bool) -> bool:
    """Whether a candidate value without a number is worst-filled.

    A candidate ``not_applicable`` is filled (a judge-side one too: ``_judge_side`` flags it so the
    gate caps its exclusion exactly like a judge error).
    """
    if value is None or value.status is MetricStatus.NOT_APPLICABLE:
        return True
    return value.status is MetricStatus.ERROR and (fill_errors or request_failed(scored))


def judge_side(value: MetricValue | None) -> bool:
    """A judge error or a judge-side ``not_applicable``: excluded unless over the 20 % cap."""
    if value is None:
        return False
    if value.status is MetricStatus.NOT_APPLICABLE:
        return value.details.get("reason") in JUDGE_SIDE_REASONS
    return value.status is MetricStatus.ERROR


def cut_ids(run: RunResults, metric: str) -> frozenset[str]:
    """Cases whose ``ok`` value of ``metric`` was computed on a truncated judge input (X3.9)."""
    found: set[str] = set()
    for scored in run.values:
        value = lookup(scored, metric)
        if value is not None and value.status is MetricStatus.OK and value.details.get("truncated"):
            found.add(str(scored.case.id))
    return frozenset(found)
