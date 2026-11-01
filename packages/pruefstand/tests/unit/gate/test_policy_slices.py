"""Slices, applicability and informational metrics through ``evaluate_gate`` (R14-R21)."""

import numpy as np
import pytest
from testsupport.builders import NA, fixture_f1, make_case, make_run
from testsupport.gate_helpers import (
    DIRECTIONS,
    FAIL,
    INSUFFICIENT,
    LOWER,
    PASS,
    POLICY,
    Edits,
    assert_invariant,
    clusters,
    everywhere,
    gate,
    row,
)

from pruefstand.gate.policy import evaluate_gate


def test_r14_perturbed_cases_only_count_in_perturbed_all() -> None:
    compound = {3 * c + 1: 0.5 for c in range(40)}
    report = gate({"context_recall": compound}, fixture=fixture_f1)
    assert row(report.decisions, "context_recall", "overall").status is PASS
    assert row(report.decisions, "context_recall", "overall").result.mean_diff == 0.0  # type: ignore[union-attr]
    assert row(report.decisions, "context_recall", "tenant", "kanzlei_mueller").status is PASS
    assert row(report.decisions, "context_recall", "lang", "de").status is PASS
    perturbed = row(report.decisions, "context_recall", "perturbed_all")
    assert perturbed.status is FAIL
    assert perturbed.result is not None
    assert perturbed.result.mean_diff == pytest.approx(-0.15)
    assert report.status is FAIL
    testable = [d for d in report.decisions if d.status is not INSUFFICIENT]
    assert len(testable) == 13
    cs = row(report.notable_slices, "context_recall", "perturbation", "compound_split")
    assert (cs.status, cs.notable, cs.gated) == (PASS, True, False)
    assert row(report.notable_slices, "context_recall", "perturbation", "typos").notable is False
    assert report.notable_slices[0] is not None
    assert (report.notable_slices[0].dimension, report.notable_slices[0].value) == (
        "perturbation",
        "compound_split",
    )
    assert report.likely_cause == "retrieval"


def test_r15_perturbed_cases_have_no_perturbed_all_pair_for_judged_metrics() -> None:
    compound = {3 * c + 1: 0.78 for c in range(40)}
    report = gate({"faithfulness": compound}, fixture=fixture_f1)
    assert row(report.decisions, "faithfulness", "overall").status is PASS
    assert not [
        d for d in report.decisions if d.metric == "faithfulness" and d.dimension == "perturbed_all"
    ]
    assert row(report.notable_slices, "faithfulness", "perturbation", "compound_split").notable
    assert report.status is PASS


def test_r20_applicability_rule() -> None:
    idx = clusters(0, 34)
    na: Edits = {"context_recall": dict.fromkeys(idx, NA)}
    report = gate(na, base_edits=na)
    rows = [d for d in (*report.decisions, *report.notable_slices) if d.metric == "context_recall"]
    assert rows
    assert not [d for d in report.decisions if d.metric == "context_recall"]
    assert all(
        d.gated is False and d.informational_reason == "applicable_clusters<30" for d in rows
    )
    assert len([d for d in report.decisions if d.status is not INSUFFICIENT]) == 6
    assert report.not_applicable_counts["context_recall"] == 70


def test_r20_small_run_is_informational() -> None:
    cases = [make_case(i, cluster=i // 2) for i in range(20)]
    base = {m: [0.0 if m in LOWER else 0.8] * 20 for m in DIRECTIONS}
    cand = {**base, "context_recall": [0.6] * 20}
    report = evaluate_gate(
        make_run("base", cases, base), make_run("cand", cases, cand), POLICY,
        np.random.default_rng(1), directions=DIRECTIONS,
    )  # fmt: skip
    assert report.status is PASS
    assert report.decisions == ()
    paired = [d for d in report.notable_slices if d.informational_reason]
    assert paired
    assert all(d.gated is False for d in paired)
    assert_invariant(report)


def test_r21_informational_mapping_removes_a_metric_from_the_decision() -> None:
    edits = everywhere("faithfulness", 0.7)
    assert gate(edits).status is FAIL
    for reason in ("tier1_judged", "judge_degraded"):
        report = gate(edits, informational={"faithfulness": reason})
        assert report.status is PASS
        rows = [d for d in report.notable_slices if d.metric == "faithfulness"]
        assert rows
        assert all(d.gated is False and d.informational_reason == reason for d in rows)
        assert not [d for d in report.decisions if d.metric == "faithfulness"]
        testable = [d for d in report.decisions if d.status is not INSUFFICIENT]
        assert len(testable) == 6  # m drops from 8 to 6


def test_r21_judge_errors_are_excluded_not_worst_filled() -> None:
    errors: Edits = {"faithfulness": dict.fromkeys(range(4), None)}
    report = gate(errors)
    overall = row(report.decisions, "faithfulness", "overall")
    assert overall.status is PASS
    assert overall.candidate_mean == pytest.approx(0.9)
    assert overall.result is not None
    assert overall.result.n_cases == 116


def test_refine_near_threshold_reruns_at_200_000() -> None:
    """SPEC §7.2: a p within 3 Monte-Carlo SE of a Holm threshold is re-run with B = 200 000."""
    compound = {3 * c + 1: 0.5 for c in range(40)}
    report = gate({"context_recall": compound}, fixture=fixture_f1)
    perturbed = row(report.decisions, "context_recall", "perturbed_all")
    assert perturbed.result is not None
    assert perturbed.result.n_resamples == 200_000
    assert perturbed.status is FAIL
    fixed = gate(everywhere("context_recall", 0.6))
    assert row(fixed.decisions, "context_recall", "overall").result.n_resamples == 2000  # type: ignore[union-attr]
