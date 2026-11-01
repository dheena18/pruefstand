"""Inputs ``evaluate_gate`` cannot judge must not pass (review of PR #22) and killing tests."""

import numpy as np
import pytest
from testsupport.builders import fixture_f0, fixture_f1, make_case, make_run
from testsupport.gate_helpers import DIRECTIONS, FAIL, PASS, POLICY, clusters, gate, row

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.gate.absolute import absolute_checks
from pruefstand.gate.policy import evaluate_gate
from pruefstand.gate.stats import minimum_detectable_effect


def _evaluate(base: RunResults, cand: RunResults) -> GateReport:
    return evaluate_gate(base, cand, POLICY, np.random.default_rng(1), directions=DIRECTIONS)


def _subset(keep: list[int]) -> tuple[RunResults, RunResults]:
    cases, values = fixture_f0()
    base = make_run("base", cases, values)
    cand = make_run(
        "cand", [cases[i] for i in keep], {m: [v[i] for i in keep] for m, v in values.items()}
    )
    return base, cand


@pytest.mark.parametrize(
    "keep",
    [
        pytest.param([], id="zero-cases"),
        pytest.param(list(range(20)), id="20-of-120"),
        pytest.param(list(range(100)), id="no-lang-en"),
    ],
)
def test_b1_candidate_with_missing_cases_is_an_input_error(keep: list[int]) -> None:
    base, cand = _subset(keep)
    with pytest.raises(GateInputError, match="case"):
        _evaluate(base, cand)


def test_b1_baseline_cases_missing_from_the_candidate_either_way() -> None:
    base, cand = _subset(list(range(120)))
    with pytest.raises(GateInputError, match="case"):
        _evaluate(cand, _subset(list(range(100)))[1])
    assert _evaluate(base, cand).status is PASS


def test_b1_changed_case_metadata_is_an_input_error() -> None:
    cases, values = fixture_f0()
    base = make_run("base", cases, values)
    moved = [make_case(i, cluster=i // 2, tenant="kanzlei_mueller", lang="en") for i in range(120)]
    with pytest.raises(GateInputError, match="differ"):
        _evaluate(base, make_run("cand", moved, values))


def test_judge_errors_and_exclusions_are_reported() -> None:
    report = gate({"faithfulness": dict.fromkeys(range(4), None)})
    assert report.n_excluded == {"faithfulness": 4}
    assert report.n_unmatched == {}
    assert gate().n_excluded == {}


def test_m4_judge_errors_up_to_the_cap_are_excluded() -> None:
    report = gate({"faithfulness": dict.fromkeys(range(24), None)})  # 24 of 120 = 20 %
    assert report.status is PASS
    assert report.n_excluded == {"faithfulness": 24}


def test_m4_errors_beyond_the_cap_fail_closed() -> None:
    report = gate({"faithfulness": dict.fromkeys(range(30), None)})  # 25 %
    assert report.status is FAIL
    assert row(report.decisions, "faithfulness", "overall").status is FAIL
    assert "faithfulness" not in report.n_excluded


def test_m4_all_cases_erroring_cannot_pass() -> None:
    report = gate({"context_recall": dict.fromkeys(range(120), None)})
    assert report.status is FAIL
    assert report.likely_cause == "retrieval"


def test_m5_error_rate_with_unknown_values_counts_as_errors() -> None:
    report = gate({"error_rate": dict.fromkeys(range(120), None)})
    rate = row(report.absolute_checks, "error_rate", "overall")
    assert rate.status is FAIL
    assert rate.candidate_mean == 1.0
    assert report.status is FAIL


@pytest.mark.parametrize("unknown", [None, float("nan")], ids=["error", "not-applicable"])
def test_m5_injection_cases_without_a_value_fail_closed(unknown: float | None) -> None:
    cases = [make_case(i, cluster=i // 2, category="injection") for i in range(40)]
    ok = {m: [v] * 40 for m, v in {**dict.fromkeys(POLICY.metrics, 0.8), "error_rate": 0.0}.items()}
    ok["injection_success"] = [0.0] * 40
    cand = {**ok, "injection_success": [unknown] * 40}
    report = _evaluate(make_run("base", cases, ok), make_run("cand", cases, cand))
    injection = row(report.absolute_checks, "injection_success", "overall")
    assert injection.status is FAIL
    assert report.status is FAIL


def test_m5_failing_perturbed_cases_are_caught_by_perturbed_all() -> None:
    """D359a: ``error_rate`` counts unperturbed cases; a broken robustness run still fails."""
    perturbed = [i for i in range(120) if i % 3 != 0]
    edits = {m: dict.fromkeys(perturbed, None) for m in DIRECTIONS if m != "error_rate"}
    edits["error_rate"] = dict.fromkeys(perturbed, 1.0)
    report = gate(edits, fixture=fixture_f1)
    assert row(report.decisions, "context_recall", "perturbed_all").status is FAIL
    assert report.status is FAIL


def test_mde_uses_the_size_of_the_single_holm_family() -> None:
    report = gate({"context_recall": dict.fromkeys(range(120), 0.6)})
    testable = [d for d in report.decisions if d.status is not GateStatus.INSUFFICIENT_DATA]
    assert len(testable) == 8
    for d in testable:
        assert d.result is not None
        assert d.mde == pytest.approx(minimum_detectable_effect(d.result.se, 0.025, 0.05, 0.8, 8))


def test_irrelevant_drops_are_never_rerun() -> None:
    """Significant (p = 1/2001, near a Holm step at m = 13) but 0.03 < max_drop: no re-run."""
    report = gate({"context_recall": dict.fromkeys(range(120), 0.77)}, fixture=fixture_f1)
    assert len([d for d in report.decisions if d.status is not GateStatus.INSUFFICIENT_DATA]) == 13
    for d in report.decisions:
        assert d.result is None or d.result.n_resamples == 2000


def test_paired_warn_raises_an_absolute_row_to_warn() -> None:
    policy = GatePolicy(
        metrics={"injection_success": MetricPolicy(max_drop=0.05, max_value=0.02)},
        n_resamples=2000,
    )
    cases, values = fixture_f0()
    run = make_run("r", cases, values)
    quiet = absolute_checks(run, run, policy, {}, {})
    assert row(quiet, "injection_success", "overall").status is PASS
    raised = absolute_checks(run, run, policy, {}, {"injection_success": GateStatus.WARN})
    assert row(raised, "injection_success", "overall").status is GateStatus.WARN
    assert row(raised, "injection_success", "overall").gated
    fail_stays = absolute_checks(run, run, policy, {}, {"injection_success": GateStatus.PASS})
    assert row(fail_stays, "injection_success", "overall").status is PASS
    assert clusters(0, 0) == [0, 1]
