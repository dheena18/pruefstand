"""Metric value model (interfaces §2, ``core.models.metric``)."""

import math
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class MetricStatus(StrEnum):
    """Outcome of computing one metric on one case."""

    OK = "ok"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class MetricKind(StrEnum):
    """Whether a metric is computed without or with an LLM judge."""

    DETERMINISTIC = "deterministic"
    JUDGED = "judged"


class MetricValue(BaseModel):
    """One metric on one case.

    ``value`` lies in [0, 1] unless ``metric == "latency_ms"`` (finite milliseconds >= 0). Status
    ``ok`` requires a value; any other status carries no value (a judge failure is ``error``
    with ``value=None``, never 0).

    Raises:
        ValidationError: ``value`` out of range, or a value given with a non-``ok`` status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    metric_version: str
    value: float | None
    status: MetricStatus
    details: dict[str, str | float | int | bool] = {}

    @model_validator(mode="after")
    def _check_value(self) -> Self:
        if self.status is not MetricStatus.OK and self.value is not None:
            msg = f"metric {self.metric}: value must be None when status is {self.status.value}"
            raise ValueError(msg)
        if self.status is MetricStatus.OK and self.value is None:
            msg = f"metric {self.metric}: status ok requires a value"
            raise ValueError(msg)
        if self.value is None:
            return self
        if self.metric == "latency_ms":
            if not math.isfinite(self.value) or self.value < 0:
                msg = f"metric latency_ms: value {self.value} must be finite and >= 0"
                raise ValueError(msg)
        elif not 0.0 <= self.value <= 1.0:
            msg = f"metric {self.metric}: value {self.value} is outside [0, 1]"
            raise ValueError(msg)
        return self
