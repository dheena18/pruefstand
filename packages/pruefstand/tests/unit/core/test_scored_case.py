"""``ScoredCase`` lists every metric once (T1.7a)."""

import pytest
from pydantic import ValidationError
from testsupport.builders import make_case

from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import ScoredCase


def _value(metric: str, value: float) -> MetricValue:
    return MetricValue(metric=metric, metric_version="1", value=value, status=MetricStatus.OK)


def test_a_metric_listed_twice_is_rejected() -> None:
    with pytest.raises(ValidationError, match="faithfulness"):
        ScoredCase(
            case=make_case(0, cluster=0),
            values=(_value("faithfulness", 1.0), _value("context_recall", 1.0),
                    _value("faithfulness", 0.0)),
        )  # fmt: skip


def test_distinct_metrics_are_accepted() -> None:
    scored = ScoredCase(
        case=make_case(0, cluster=0),
        values=(_value("faithfulness", 1.0), _value("context_recall", 1.0)),
    )
    assert [v.metric for v in scored.values] == ["faithfulness", "context_recall"]
