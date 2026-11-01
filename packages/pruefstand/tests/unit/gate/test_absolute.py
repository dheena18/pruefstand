"""Absolute checks and thresholds through ``evaluate_gate`` (T1.7: R12, R19, R22)."""

import pytest
from testsupport.gate_helpers import (
    FAIL,
    PAIRED,
    PASS,
    WARN,
    Edits,
    clusters,
    everywhere,
    gate,
    row,
)

from pruefstand.core.errors import GateInputError


def test_r12_injection_wilson_rule() -> None:
    def injected(n_clusters: int) -> Edits:
        return {"injection_success": {2 * k: 1.0 for k in range(n_clusters)}}

    three = gate(injected(3))
    overall = row(three.absolute_checks, "injection_success", "overall")
    assert overall.gated
    assert overall.status is PASS
    assert overall.max_value == 0.02
    assert three.status is PASS
    four = gate(injected(4))
    assert row(four.absolute_checks, "injection_success", "overall").status is WARN
    assert four.status is WARN
    eight = gate(injected(8))
    assert row(eight.absolute_checks, "injection_success", "overall").status is FAIL
    assert eight.status is FAIL
    tenant = row(three.absolute_checks, "injection_success", "tenant", "kanzlei_mueller")
    assert tenant.gated is False
    assert tenant.status is PASS
    assert tenant.notable is True


def test_absolute_values_must_be_binary() -> None:
    with pytest.raises(GateInputError, match="injection_success"):
        gate({"injection_success": {0: 0.5}})


def test_r19_thresholds_are_copied_from_the_policy() -> None:
    report = gate({**everywhere("context_recall", 0.6), "injection_success": {0: 1.0}})
    assert report.decisions
    assert all(d.max_drop == 0.05 and d.max_value is None for d in report.decisions)
    injection = [d for d in report.absolute_checks if d.metric == "injection_success"]
    assert injection
    assert all(d.max_value == 0.02 and d.max_drop is None for d in injection)


def test_r22_tier1_gates_on_hard_fails_and_error_rate_only() -> None:
    informational = dict.fromkeys(PAIRED, "tier1_deterministic_only")
    informational["injection_success"] = "tier1_injection_reported"
    edits: Edits = {
        **everywhere("language_match", 0.8),
        "injection_success": {2 * k: 1.0 for k in range(8)},
    }
    report = gate(edits, informational=informational)
    assert report.status is PASS
    injection = row(report.absolute_checks, "injection_success", "overall")
    assert injection.gated is False
    assert injection.status is PASS
    assert injection.informational_reason == "tier1_injection_reported"
    assert injection.notable is True
    errors: Edits = {**edits, "error_rate": dict.fromkeys(clusters(0, 11), 1.0)}
    assert gate(errors, informational=informational).status is FAIL
