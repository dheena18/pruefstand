"""Common base of the per-case deterministic metrics (applicability and ``requires`` handling)."""

from pruefstand.core.enums import Category
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase

Details = dict[str, str | float | int | bool]


class BaseMetric:
    """Template for a metric computed from one ``TestCase`` and one ``TargetResponse``.

    Subclasses set ``name``, ``higher_is_better`` (and optionally ``requires`` / ``applies_to``)
    and implement ``_compute``. ``compute`` returns ``not_applicable`` (never a silent 0) when the
    category is outside ``applies_to`` or a ``requires`` field is missing, so ``_compute`` can
    assume both hold. Subclasses must not raise on any model output.
    """

    name: str
    version: str = "1"
    kind: MetricKind = MetricKind.DETERMINISTIC
    higher_is_better: bool
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    def compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        """Compute the metric for one case.

        Args:
            case: The test case.
            resp: The target's response (untrusted model output).

        Returns:
            A ``MetricValue``: ``ok`` with a value in [0, 1], ``not_applicable`` or ``error``.
        """
        if self.applies_to is not None and case.category not in self.applies_to:
            return self.na("category")
        missing = self._missing_field(resp)
        if missing is not None:
            return self.na(missing)
        return self._compute(case, resp)

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        raise NotImplementedError

    def _missing_field(self, resp: TargetResponse) -> str | None:
        if "chunks" in self.requires and resp.chunks is None:
            return "missing_chunks"
        if "chunks.tenant_id" in self.requires and any(
            c.tenant_id is None for c in resp.chunks or ()
        ):
            return "missing_tenant_id"
        return None

    def ok(self, value: float, **details: str | float | int | bool) -> MetricValue:
        """Return an ``ok`` value, clamped to [0, 1] against float noise."""
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=min(1.0, max(0.0, value)),
            status=MetricStatus.OK,
            details=dict(details),
        )

    def na(self, reason: str) -> MetricValue:
        """Return a ``not_applicable`` value carrying the reason."""
        return self._without_value(MetricStatus.NOT_APPLICABLE, {"reason": reason})

    def error(self, code: str) -> MetricValue:
        """Return an ``error`` value (bad dataset input), never an exception."""
        return self._without_value(MetricStatus.ERROR, {"error": code})

    def _without_value(self, status: MetricStatus, details: Details) -> MetricValue:
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=None,
            status=status,
            details=details,
        )
