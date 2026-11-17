"""T6.3 S3: the shipped gate block equals the SPEC's over the union of keys."""

import yaml
from noise.check_consistency import REPO, differences, main, spec_gate


def _gates() -> tuple[dict[str, object], dict[str, object]]:
    shipped = yaml.safe_load((REPO / "pruefstand.yaml").read_text(encoding="utf-8"))["gate"]
    return shipped, spec_gate((REPO / "docs/spec/SPEC.md").read_text(encoding="utf-8"))


def test_the_shipped_policy_matches_the_spec() -> None:
    shipped, spec = _gates()
    assert differences(shipped, spec) == []
    assert main([]) == 0


def test_a_changed_delta_is_reported_unless_a_decision_records_it() -> None:
    shipped, spec = _gates()
    shipped["metrics"]["faithfulness"]["max_drop"] = 0.08  # type: ignore[index]  # YAML mapping
    expected = "gate.metrics.faithfulness.max_drop: shipped 0.08, SPEC 0.05"
    assert differences(shipped, spec) == [expected]
    assert differences(shipped, spec, {"gate.metrics.faithfulness.max_drop": "D9999"}) == []


def test_unlisted_keys_and_rules_are_compared_too() -> None:
    shipped, spec = _gates()
    shipped["new_setting"] = 1
    shipped["metrics"]["faithfulness"]["confidence"] = 0.9  # type: ignore[index]  # YAML mapping
    assert differences(shipped, spec) == [
        "gate.new_setting: shipped 1, SPEC None",
        "gate.metrics.faithfulness.confidence: shipped 0.9, SPEC 0.95",
    ]


def test_a_metric_missing_on_one_side_is_reported() -> None:
    shipped, spec = _gates()
    del shipped["metrics"]["language_match"]  # type: ignore[attr-defined]  # YAML mapping
    assert differences(shipped, spec) == [
        "gate.metrics.language_match.confidence: shipped None, SPEC 0.95",
        "gate.metrics.language_match.max_drop: shipped None, SPEC 0.03",
    ]
