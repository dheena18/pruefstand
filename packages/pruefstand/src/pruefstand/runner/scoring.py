"""Deterministic metric values of one case, including the not-applicable and error rules."""

from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.target import CaseRecord
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import Metric
from pruefstand.metrics.deterministic.record import ErrorRateMetric, LatencyMetric
from pruefstand.metrics.registry import MetricRegistry, evaluate_deterministic
from pruefstand.runner.routing import Route

RETRIEVAL_METRICS = frozenset({"context_recall", "ndcg_at_k", "tenant_leak"})
"""Metrics computed for ``mode == "retrieve"`` records; other answer metrics are not_applicable."""


def _without_value(m: Metric, status: MetricStatus, key: str, detail: str) -> MetricValue:
    return MetricValue(
        metric=m.name, metric_version=m.version, value=None, status=status, details={key: detail}
    )


def not_applicable(m: Metric, reason: str) -> MetricValue:
    """A ``not_applicable`` value (never a 0) carrying ``details["reason"]``."""
    return _without_value(m, MetricStatus.NOT_APPLICABLE, "reason", reason)


def target_error(m: Metric) -> MetricValue:
    """An ``error`` value for a metric whose case request finally failed."""
    return _without_value(m, MetricStatus.ERROR, "error", "target_error")


def deterministic_values(
    case: TestCase, record: CaseRecord, route: Route, registry: MetricRegistry
) -> dict[str, MetricValue]:
    """Compute every deterministic metric of the registry for one case.

    The evaluation is synchronous on purpose: metrics share a wall-clock regex budget
    (``normalise.REGEX_TIMEOUT_S``), so running them one after the other inside the event loop
    keeps that budget honest even at ``concurrency > 1``.

    Args:
        case: The test case.
        record: The case's exchange with the target.
        route: How the case was routed; in ``retrieve`` mode only ``RETRIEVAL_METRICS`` run.
        registry: The metrics.

    Returns:
        Name -> value, in registry order. A failed request gives ``error`` values (and
        ``error_rate = 1``); categories outside a metric's ``applies_to`` stay not_applicable.
    """
    values: dict[str, MetricValue] = {}
    to_compute: list[Metric] = []
    for m in registry.all():
        if m.kind is MetricKind.JUDGED:
            continue
        if isinstance(m, ErrorRateMetric):
            values[m.name] = m.from_record(record)
        elif isinstance(m, LatencyMetric):
            values[m.name] = target_error(m) if record.error else m.from_record(record)
        elif m.applies_to is not None and case.category not in m.applies_to:
            values[m.name] = not_applicable(m, "category")
        elif route.mode == "retrieve" and m.name not in RETRIEVAL_METRICS:
            values[m.name] = not_applicable(m, route.reason or "retrieve_mode")
        elif record.response is None:
            values[m.name] = target_error(m)
        else:
            to_compute.append(m)
    if record.response is not None:
        for value in evaluate_deterministic(case, record.response, to_compute):
            values[value.metric] = value
    order = [m.name for m in registry.all() if m.name in values]
    return {name: values[name] for name in order}
