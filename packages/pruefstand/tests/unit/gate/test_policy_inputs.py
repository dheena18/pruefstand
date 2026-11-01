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
    # 24 of 120 = 20 %, spread so that no slice (tenant, lang) is above 20 % either
    report = gate({"faithfulness": dict.fromkeys(range(0, 120, 5), None)})
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
    ok: dict[str, list[float | None]] = {
        m: [v] * 40 for m, v in {**dict.fromkeys(POLICY.metrics, 0.8), "error_rate": 0.0}.items()
    }
    ok["injection_success"] = [0.0] * 40
    ok.update({m: [0.0] * 40 for m in HARD})
    cand: dict[str, list[float | None]] = {**ok, "injection_success": [unknown] * 40}
    report = _evaluate(make_run("base", cases, ok), make_run("cand", cases, cand))
    injection = row(report.absolute_checks, "injection_success", "overall")
    assert injection.status is FAIL
    assert report.status is FAIL


def test_m5_failing_perturbed_cases_are_caught_by_perturbed_all() -> None:
    """D359a: ``error_rate`` counts unperturbed cases; a broken robustness run still fails."""
    perturbed = [i for i in range(120) if i % 3 != 0]
    edits: dict[str, dict[int, float | None]] = {
        m: dict.fromkeys(perturbed, None) for m in DIRECTIONS if m != "error_rate"
    }
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


HARD = {"canary_leak": 0.0, "tenant_leak": 0.0, "system_prompt_leak": 0.0}


def _custom(
    n_clusters: int,
    per_cluster: int,
    cand_edit: dict[int, float | None],
    *,
    metric: str = "faithfulness",
    cand_value: float = 0.9,
    en_clusters: int = 0,
    en_last: int = 0,
    base_edit: dict[int, float | None] | None = None,
) -> GateReport:
    n = n_clusters * per_cluster
    cases = [
        make_case(
            i,
            cluster=i // per_cluster,
            lang="en"
            if i // per_cluster < en_clusters or i // per_cluster >= n_clusters - en_last
            else "de",
        )
        for i in range(n)
    ]
    others = {"context_recall": 0.8, "citation_recall": 0.7, "language_match": 1.0}
    base: dict[str, list[float | None]] = {
        m: [v] * n for m, v in {**others, "faithfulness": 0.9, "error_rate": 0.0, **HARD}.items()
    }
    base["injection_success"] = [0.0] * n
    for i, v in (base_edit or {}).items():
        base[metric][i] = v
    cand = {k: list(v) for k, v in base.items()}
    cand[metric] = [cand_value] * n
    for i, v in cand_edit.items():
        cand[metric][i] = v
    return _evaluate(make_run("base", cases, base), make_run("cand", cases, cand))


def test_m1_a_slice_that_loses_its_cases_to_judge_errors_cannot_vanish() -> None:
    """300 one-case clusters, 60 of them lang=en: all 60 judge-errored, the rest unchanged."""
    report = _custom(300, 1, dict.fromkeys(range(60), None), en_clusters=60)
    en = row(report.decisions, "faithfulness", "lang", "en")
    assert en.status is FAIL
    assert report.status is FAIL
    control = _custom(300, 1, dict.fromkeys(range(60), 0.0), en_clusters=60)
    assert row(control.decisions, "faithfulness", "lang", "en").status is FAIL


def test_m1_exclusion_cannot_push_overall_below_the_cluster_minimum() -> None:
    """35 clusters of 3; 7 whole clusters judge-errored (20 %); faithfulness 0.4 vs 0.9."""
    report = _custom(35, 3, dict.fromkeys(range(21), None), cand_value=0.4)
    overall = row(report.decisions, "faithfulness", "overall")
    assert overall.informational_reason is None
    assert overall.status is FAIL
    assert report.status is FAIL


def test_m1_small_exclusions_stay_excluded_per_slice() -> None:
    report = _custom(300, 1, dict.fromkeys(range(5), None), en_clusters=60)
    assert row(report.decisions, "faithfulness", "lang", "en").status is PASS
    assert report.n_excluded == {"faithfulness": 5}


def test_empty_baseline_is_an_input_error() -> None:
    empty = make_run("base", [], {m: [] for m in DIRECTIONS})
    cases, values = fixture_f0()
    with pytest.raises(GateInputError, match="no cases"):
        _evaluate(empty, make_run("cand", cases, values))


def test_metric_without_usable_baseline_values_is_an_input_error() -> None:
    cases, values = fixture_f0()
    values = {**values, "faithfulness": [float("nan")] * 120}
    with pytest.raises(GateInputError, match="faithfulness"):
        _evaluate(make_run("base", cases, values), make_run("cand", cases, fixture_f0()[1]))


def test_duplicated_case_ids_are_an_input_error() -> None:
    policy = GatePolicy(metrics={"error_rate": MetricPolicy(max_value=0.02)}, n_resamples=2000)
    cases = [make_case(i, cluster=i) for i in range(10)]
    base = make_run("base", cases, {**{m: [0.0] * 10 for m in HARD}, "error_rate": [0.0] * 10})
    erring = [1.0] + [0.0] * 9
    bad_cases = cases * 10
    cand = make_run(
        "cand", bad_cases, {**{m: [0.0] * 100 for m in HARD}, "error_rate": erring + [0.0] * 90}
    )
    with pytest.raises(GateInputError, match="duplicate"):
        evaluate_gate(base, cand, policy, np.random.default_rng(1), directions=DIRECTIONS)


def test_m1_errors_hiding_a_small_untestable_slice_are_filled_everywhere() -> None:
    """The last 29 of 300 one-case clusters are lang=en (< min_clusters), all judge-errored."""
    errors = dict.fromkeys(range(271, 300), None)
    report = _custom(300, 1, errors, en_last=29)
    assert report.status is FAIL
    assert row(report.decisions, "faithfulness", "overall").status is FAIL
    control = _custom(300, 1, dict.fromkeys(range(271, 300), 0.0), en_last=29)
    assert control.status is FAIL


def test_m2_baseline_errors_on_a_whole_slice_are_an_input_error() -> None:
    en = range(60)
    with pytest.raises(GateInputError, match="baseline"):
        _custom(300, 1, dict.fromkeys(en, 0.0), en_clusters=60, base_edit=dict.fromkeys(en, None))


def test_m2_a_slice_without_baseline_values_is_still_listed() -> None:
    en = range(60)
    report = _custom(
        300, 1, dict.fromkeys(en, 0.0), en_clusters=60, base_edit=dict.fromkeys(en, float("nan"))
    )
    listed = row(report.decisions, "faithfulness", "lang", "en")
    assert listed.status is GateStatus.INSUFFICIENT_DATA
