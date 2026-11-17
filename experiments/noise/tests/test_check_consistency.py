"""T6.3 S3: the shipped thresholds equal the SPEC's gate block, differences are reported."""

import yaml
from noise.check_consistency import REPO, differences, main, spec_gate


def _gates() -> tuple[dict, dict]:  # type: ignore[type-arg]  # plain YAML mappings
    shipped = yaml.safe_load((REPO / "pruefstand.yaml").read_text(encoding="utf-8"))["gate"]
    return shipped, spec_gate((REPO / "docs/spec/SPEC.md").read_text(encoding="utf-8"))


def test_the_shipped_policy_matches_the_spec() -> None:
    shipped, spec = _gates()
    assert differences(shipped, spec) == []
    assert main([]) == 0


def test_a_changed_delta_is_reported_unless_a_decision_records_it() -> None:
    shipped, spec = _gates()
    shipped["metrics"]["faithfulness"]["max_drop"] = 0.08
    assert differences(shipped, spec) == [
        "gate.metrics.faithfulness.max_drop: shipped 0.08, SPEC 0.05"
    ]
    recorded = {"gate.metrics.faithfulness.max_drop": "D9999"}
    assert differences(shipped, spec, recorded) == []


def test_a_metric_missing_on_one_side_is_reported() -> None:
    shipped, spec = _gates()
    del shipped["metrics"]["language_match"]
    assert differences(shipped, spec) == [
        "gate.metrics.language_match.max_drop: shipped None, SPEC 0.03"
    ]
