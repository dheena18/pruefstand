"""The informational mapping for judged metrics (T5.2b S8, round 9 X3.9, round 11 Y4.4)."""

from pathlib import Path

import pytest
from testsupport.run_builders import make_case, make_manifest

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import RunManifest, ScoredCase
from pruefstand.judges.calibration import judges_uncalibrated, read_status, refusal_judge_passed
from pruefstand.pipeline.gate import informational_mapping

POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
        "answer_correctness": MetricPolicy(max_drop=0.05),
    }
)
JUDGED = ("faithfulness", "answer_correctness")


def pair(**changes: object) -> tuple[RunManifest, RunManifest]:
    fields = {
        "stack": "a40", "workload": "nightly", "splits": (Split.FULL,), "judge_mode": "local",
        **changes,
    }  # fmt: skip
    return (
        make_manifest(run_id="20261102T220000-aaaaaa", **fields),
        make_manifest(run_id="20261102T220001-bbbbbb", **fields),
    )


def scored(truncated: int, total: int) -> list[ScoredCase]:
    rows = []
    for i in range(total):
        details: dict[str, str | float | int | bool] = {"truncated": True} if i < truncated else {}
        value = MetricValue(
            metric="faithfulness", metric_version="1", value=1.0, status=MetricStatus.OK,
            details=details,
        )  # fmt: skip
        rows.append(ScoredCase(case=make_case(i), values=(value,)))
    return rows


def test_a_clean_tier_two_run_has_an_empty_mapping() -> None:
    base, cand = pair()
    assert informational_mapping(base, cand, POLICY, values=scored(0, 40)) == {}


def test_tier_one_maps_every_judged_metric_to_tier1_judged() -> None:
    base, cand = pair(stack="live", workload="pr", splits=(Split.SMOKE,))
    mapping = informational_mapping(base, cand, POLICY)
    assert {mapping[m] for m in JUDGED} == {"tier1_judged"}


def test_a_degraded_judge_in_tier_two_is_judge_degraded() -> None:
    base, cand = pair()
    degraded = cand.model_copy(update={"judge_degraded": True})
    mapping = informational_mapping(base, degraded, POLICY)
    assert {mapping[m] for m in JUDGED} == {"judge_degraded"}
    assert "context_recall" not in mapping


def test_no_passing_judge_in_the_calibration_file_is_judge_uncalibrated() -> None:
    base, cand = pair()
    mapping = informational_mapping(base, cand, POLICY, uncalibrated=True)
    assert {mapping[m] for m in JUDGED} == {"judge_uncalibrated"}
    assert "context_recall" not in mapping


def test_three_truncated_of_forty_is_judge_truncated_two_of_forty_is_not() -> None:
    base, cand = pair()
    seven_and_a_half = informational_mapping(base, cand, POLICY, values=scored(3, 40))
    five = informational_mapping(base, cand, POLICY, values=scored(2, 40))
    assert seven_and_a_half == {"faithfulness": "judge_truncated"}
    assert five == {}


def test_a_fallback_judge_on_either_run_marks_every_judged_metric_and_no_other() -> None:
    base, cand = pair()
    mapping = informational_mapping(
        base, cand.model_copy(update={"judge_fallback": True}), POLICY, values=scored(0, 40)
    )
    assert mapping == dict.fromkeys(JUDGED, "judge_fallback")


def test_the_calibration_status_file(tmp_path: Path) -> None:
    assert read_status(tmp_path / "missing.yaml") is None
    assert not judges_uncalibrated(tmp_path / "missing.yaml")
    passing = tmp_path / "a.yaml"
    passing.write_text("epoch: 1\npassed: true\nrefusal_judged: {passed: true}\n", encoding="utf-8")
    failing = tmp_path / "b.yaml"
    failing.write_text("epoch: 2\npassed: false\n", encoding="utf-8")
    assert refusal_judge_passed(passing)
    assert not judges_uncalibrated(passing)
    assert judges_uncalibrated(failing)
    assert not refusal_judge_passed(failing)


def test_a_broken_calibration_file_is_a_config_error(tmp_path: Path) -> None:
    broken = tmp_path / "c.yaml"
    broken.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_status(broken)


def test_a_tier_two_run_without_a_judge_makes_every_judged_metric_informational() -> None:
    base, cand = pair()
    skipped = cand.model_copy(update={"judge_mode": "skipped"})
    mapping = informational_mapping(base, skipped, POLICY)
    assert dict.fromkeys(JUDGED, "judge_skipped").items() <= mapping.items()
    assert "context_recall" not in mapping
