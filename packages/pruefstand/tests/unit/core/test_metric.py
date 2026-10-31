import pytest
from pydantic import ValidationError

from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue


def make(metric: str, value: float | None, status: MetricStatus = MetricStatus.OK) -> MetricValue:
    return MetricValue(metric=metric, metric_version="1", value=value, status=status)


def test_value_above_one_is_an_error() -> None:
    with pytest.raises(ValidationError, match="context_recall"):
        make("context_recall", 1.2)


def test_negative_value_is_an_error() -> None:
    with pytest.raises(ValidationError, match="context_recall"):
        make("context_recall", -0.1)


def test_nan_is_an_error() -> None:
    with pytest.raises(ValidationError, match="context_recall"):
        make("context_recall", float("nan"))


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_bounds_are_inclusive(value: float) -> None:
    assert make("faithfulness", value).value == value


def test_latency_may_exceed_one() -> None:
    assert make("latency_ms", 834.0).value == 834.0


@pytest.mark.parametrize("status", [MetricStatus.NOT_APPLICABLE, MetricStatus.ERROR])
def test_non_ok_status_has_no_value(status: MetricStatus) -> None:
    with pytest.raises(ValidationError, match="value"):
        make("context_recall", 0.0, status)
    assert make("context_recall", None, status).value is None


def test_details_keep_their_types() -> None:
    m = MetricValue(
        metric="faithfulness",
        metric_version="2",
        value=0.5,
        status=MetricStatus.OK,
        details={"truncated": True, "n": 3, "share": 0.25, "reason": "x"},
    )
    again = MetricValue.model_validate_json(m.model_dump_json())
    assert again == m
    assert again.details["truncated"] is True


def test_kind_values() -> None:
    assert MetricKind("judged") is MetricKind.JUDGED
