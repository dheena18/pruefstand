"""Metrics computed from the ``CaseRecord`` (runner, T1.8), not from case and response."""

import math

from pruefstand.core.enums import Category
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.target import CaseRecord


class ErrorRateMetric:
    """``error_rate``: 1.0 if the target errored or timed out on the case, else 0.0."""

    name = "error_rate"
    version = "1"
    kind = MetricKind.DETERMINISTIC
    higher_is_better = False
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    @staticmethod
    def from_record(record: CaseRecord) -> MetricValue:
        """Return 1.0 when ``record.error`` is set, else 0.0."""
        return MetricValue(
            metric=ErrorRateMetric.name,
            metric_version=ErrorRateMetric.version,
            value=0.0 if record.error is None else 1.0,
            status=MetricStatus.OK,
        )


class LatencyMetric:
    """``latency_ms``: the record's latency in milliseconds (report-only, lower is better)."""

    name = "latency_ms"
    version = "1"
    kind = MetricKind.DETERMINISTIC
    higher_is_better = False
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    @staticmethod
    def from_record(record: CaseRecord) -> MetricValue:
        """Return ``record.latency_ms``; a non-finite or negative latency is an ``error`` value."""
        latency = record.latency_ms
        if not math.isfinite(latency) or latency < 0:
            return MetricValue(
                metric=LatencyMetric.name,
                metric_version=LatencyMetric.version,
                value=None,
                status=MetricStatus.ERROR,
                details={"error": "invalid_latency"},
            )
        return MetricValue(
            metric=LatencyMetric.name,
            metric_version=LatencyMetric.version,
            value=latency,
            status=MetricStatus.OK,
        )
