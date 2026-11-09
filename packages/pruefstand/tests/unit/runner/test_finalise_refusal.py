"""``finalise_refusal`` (round 9 D9-15)."""

from testsupport.run_builders import make_case

from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.runner.refusal import finalise_refusal


def value(name: str, number: float | None, status: MetricStatus = MetricStatus.OK) -> MetricValue:
    return MetricValue(
        metric=name, metric_version="1", value=number, status=status,
        details={} if number is not None else {"reason": "x"},
    )  # fmt: skip


def judged(number: float, source: str) -> dict[str, MetricValue]:
    verdict = MetricValue(
        metric="refusal_judged", metric_version="1", value=number, status=MetricStatus.OK,
        details={"refused_source": source},
    )  # fmt: skip
    return {"refusal_judged": verdict}


def test_a_judge_refusal_turns_both_metrics_to_one() -> None:
    values = {
        "refusal_correct": value("refusal_correct", 0.0),
        "false_refusal": value("false_refusal", 0.0),
    }
    out = finalise_refusal(make_case(0), values, judged(1.0, "judge"))
    assert [out[m].value for m in values] == [1.0, 1.0]
    assert {out[m].details["refused_source"] for m in values} == {"judge"}


def test_a_phrase_decision_keeps_its_value_and_is_marked_phrase() -> None:
    values = {"refusal_correct": value("refusal_correct", 1.0)}
    out = finalise_refusal(make_case(0), values, judged(1.0, "phrase"))
    assert out["refusal_correct"].value == 1.0
    assert out["refusal_correct"].details["refused_source"] == "phrase"


def test_a_judge_that_says_not_refused_changes_nothing() -> None:
    values = {"false_refusal": value("false_refusal", 0.0)}
    out = finalise_refusal(make_case(0), values, judged(0.0, "judge"))
    assert out["false_refusal"].value == 0.0
    assert out["false_refusal"].details["refused_source"] == "phrase"


def test_errors_and_not_applicable_values_are_left_alone() -> None:
    na = value("refusal_correct", None, MetricStatus.NOT_APPLICABLE)
    out = finalise_refusal(make_case(0), {"refusal_correct": na}, judged(1.0, "judge"))
    assert out["refusal_correct"] == na
