"""The informational mapping for judged metrics (T5.2b S8, round 9 X3.9, round 11 Y4.4)."""

from pathlib import Path

import pytest
from testsupport.run_builders import make_manifest

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunManifest
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


def test_a_clean_tier_two_run_has_an_empty_mapping() -> None:
    base, cand = pair()
    assert informational_mapping(base, cand, POLICY) == {}


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


def test_truncation_of_the_candidate_is_never_a_reason_to_stop_gating() -> None:
    base, cand = pair()
    cand = cand.model_copy(update={"judged_cases": 40, "counts": {"judge_truncated": 40}})
    assert informational_mapping(base, cand, POLICY) == {}  # D815: it counts against the candidate


def test_a_fallback_judge_on_either_run_marks_every_judged_metric_and_no_other() -> None:
    base, cand = pair()
    mapping = informational_mapping(base, cand.model_copy(update={"judge_fallback": True}), POLICY)
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
