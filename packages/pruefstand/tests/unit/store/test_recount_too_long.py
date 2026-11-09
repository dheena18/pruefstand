"""``_recount`` of a projected release run counts too-long judge inputs as judged (D814)."""

from testsupport.run_builders import make_case

from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import ScoredCase
from pruefstand.store.promote import _recount


def test_a_too_long_input_is_a_judged_and_truncated_case() -> None:
    value = MetricValue(
        metric="faithfulness",
        metric_version="2",
        value=None,
        status=MetricStatus.NOT_APPLICABLE,
        details={"reason": "judge_input_too_long"},
    )
    other = MetricValue(
        metric="faithfulness",
        metric_version="2",
        value=None,
        status=MetricStatus.NOT_APPLICABLE,
        details={"reason": "category"},
    )
    kept = (
        ScoredCase(case=make_case(0), values=(value,)),
        ScoredCase(case=make_case(1), values=(other,)),
    )
    counts, judged = _recount((), kept)
    assert judged == 1
    assert counts["judge_truncated"] == 1
