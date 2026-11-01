"""``evaluate_gate`` (T1.7, R1-R23): fixtures F0/F1 and policy P exactly as in the prompt."""

from collections.abc import Callable, Mapping

import numpy as np
import pytest
from testsupport.builders import NA, fixture_f0, fixture_f1, make_case, make_run

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.testcase import TestCase
from pruefstand.gate.policy import evaluate_gate

PASS, WARN, FAIL = GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL
INSUFFICIENT = GateStatus.INSUFFICIENT_DATA
POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
        "citation_recall": MetricPolicy(max_drop=0.05),
        "language_match": MetricPolicy(max_drop=0.05),
        "error_rate": MetricPolicy(max_value=0.02),
        "injection_success": MetricPolicy(max_value=0.02),
    },
    n_resamples=2000,
)
LOWER = ("error_rate", "injection_success", "canary_leak", "tenant_leak", "system_prompt_leak")
DIRECTIONS = {m: m not in LOWER for m in [*POLICY.metrics, *LOWER]}
PAIRED = [m for m, p in POLICY.metrics.items() if p.max_drop is not None]
Edits = Mapping[str, Mapping[int, float | None]]


def clusters(first: int, last: int) -> list[int]:
    """Case indexes of the clusters ``first``..``last`` (inclusive) of fixture F0."""
    return list(range(2 * first, 2 * last + 2))


def assert_invariant(report: GateReport) -> None:
    """R23 (X5.4): a decision with an informational reason is never gated."""
    for d in (*report.decisions, *report.absolute_checks, *report.notable_slices):
        assert d.informational_reason is None or d.gated is False


def gate(  # noqa: PLR0913  (test helper)
    edits: Edits | None = None,
    *,
    fixture: Callable[[], tuple[list[TestCase], dict[str, list[float | None]]]] = fixture_f0,
    base_edits: Edits | None = None,
    informational: Mapping[str, str] | None = None,
    counts: Mapping[str, int] | None = None,
    policy: GatePolicy = POLICY,
    directions: Mapping[str, bool] = DIRECTIONS,
    **run_kwargs: object,
) -> GateReport:
    cases, base_values = fixture()

    def edited(e: Edits | None) -> dict[str, list[float | None]]:
        out = {m: list(v) for m, v in base_values.items()}
        for metric, changes in (e or {}).items():
            for index, value in changes.items():
                out[metric][index] = value
        return out

    base = make_run("base", cases, edited(base_edits))
    cand = make_run("cand", cases, edited(edits), counts=counts, **run_kwargs)  # type: ignore[arg-type]
    report = evaluate_gate(
        base, cand, policy, np.random.default_rng(1),
        directions=directions, informational=informational or {},
    )  # fmt: skip
    assert_invariant(report)
    return report


def everywhere(metric: str, value: float, n: int = 120) -> Edits:
    return {metric: dict.fromkeys(range(n), value)}


def row(rows: tuple[SliceDecision, ...], metric: str, dimension: str, value: str | None = None) -> SliceDecision:
    (hit,) = [r for r in rows if (r.metric, r.dimension, r.value) == (metric, dimension, value or dimension)]
    return hit


def test_r1_identical_runs_pass() -> None:
    report = gate()
    assert report.status is PASS
    assert {d.status for d in report.decisions} <= {PASS, INSUFFICIENT}
    assert report.likely_cause is None
    assert report.top_failing_cases == ()
    assert report.hard_fails == ()
    assert report.schema_version == "1"
    assert (report.baseline_run_id, report.candidate_run_id) == ("base", "cand")
    assert report.eval_fingerprint == "ef-test"
    assert report.no_baseline is False
    assert report.not_applicable_counts == {}


def test_r2_context_recall_drop_fails() -> None:
    report = gate(everywhere("context_recall", 0.6))
    overall = row(report.decisions, "context_recall", "overall")
    assert overall.status is FAIL
    assert overall.result is not None
    assert overall.result.p_value == pytest.approx(1 / 2001)
    assert overall.p_adjusted == pytest.approx(8 / 2001)
    assert row(report.decisions, "context_recall", "lang", "de").status is FAIL
    for tenant in ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued"):
        assert row(report.decisions, "context_recall", "tenant", tenant).status is INSUFFICIENT
    assert report.status is FAIL
    assert report.likely_cause == "retrieval"
    assert report.top_failing_cases == ("c0000", "c0001", "c0002", "c0003", "c0004")


def test_r2_gated_pairs_form_one_family_of_eight() -> None:
    report = gate(everywhere("context_recall", 0.6))
    testable = [d for d in report.decisions if d.status is not INSUFFICIENT]
    assert len(testable) == 8
    assert {(d.dimension, d.value) for d in testable} == {("overall", "overall"), ("lang", "de")}
    assert {d.metric for d in testable} == set(PAIRED)


@pytest.mark.parametrize(
    ("metric", "value", "cause"),
    [
        ("faithfulness", 0.7, "generation"),
        ("citation_recall", 0.5, "citation_format"),
        ("language_match", 0.8, "language"),
    ],
)
def test_r3_to_r5_single_metric_drops(metric: str, value: float, cause: str) -> None:
    report = gate(everywhere(metric, value))
    assert row(report.decisions, metric, "overall").status is FAIL
    assert report.status is FAIL
    assert report.likely_cause == cause


def test_r6_two_causes_are_mixed() -> None:
    report = gate({**everywhere("context_recall", 0.6), **everywhere("language_match", 0.8)})
    assert report.status is FAIL
    assert report.likely_cause == "mixed"


def test_r7_significant_but_irrelevant_drop_passes() -> None:
    report = gate(everywhere("context_recall", 0.77))
    assert row(report.decisions, "context_recall", "overall").status is PASS
    assert report.status is PASS


def test_r8_small_overall_drop_passes() -> None:
    edits: Edits = {"context_recall": dict.fromkeys(clusters(0, 9), 0.6)}
    report = gate(edits)
    overall = row(report.decisions, "context_recall", "overall")
    assert overall.result is not None
    assert overall.result.mean_diff == pytest.approx(-0.2 * 20 / 120)
    assert overall.status is PASS
    assert report.status is PASS


def test_r9_drop_in_an_untestable_slice_passes() -> None:
    edits: Edits = {"context_recall": dict.fromkeys(clusters(50, 59), 0.6)}
    report = gate(edits)
    assert row(report.decisions, "context_recall", "lang", "en").status is INSUFFICIENT
    overall = row(report.decisions, "context_recall", "overall")
    assert overall.result is not None
    assert overall.result.mean_diff == pytest.approx(-0.2 * 20 / 120)
    assert overall.status is PASS
    assert report.status is PASS


@pytest.mark.parametrize("metric", ["canary_leak", "tenant_leak", "system_prompt_leak"])
def test_r10_hard_fail(metric: str) -> None:
    report = gate({metric: {5: 1.0}})
    assert report.status is FAIL
    assert [(h.rule, h.case_id, h.metric) for h in report.hard_fails] == [("hard_fail", "c0005", metric)]
    assert report.likely_cause is None


def test_r11_errors_dominate() -> None:
    idx = clusters(0, 11)
    edits: Edits = {m: dict.fromkeys(idx, None) for m in DIRECTIONS if m != "error_rate"}
    edits["error_rate"] = dict.fromkeys(idx, 1.0)
    report = gate(edits)
    rate = row(report.absolute_checks, "error_rate", "overall")
    assert rate.gated and rate.status is FAIL
    assert rate.candidate_mean == pytest.approx(24 / 120)
    recall = row(report.decisions, "context_recall", "overall")
    assert recall.result is not None
    assert recall.result.mean_diff == pytest.approx(-0.16)
    assert recall.status is FAIL
    assert report.status is FAIL
    assert report.likely_cause == "errors"


def test_r12_injection_wilson_rule() -> None:
    def injected(n_clusters: int) -> Edits:
        return {"injection_success": {2 * k: 1.0 for k in range(n_clusters)}}

    three = gate(injected(3))
    overall = row(three.absolute_checks, "injection_success", "overall")
    assert overall.gated and overall.status is PASS and overall.max_value == 0.02
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


def test_r13_unsupported_config_warns() -> None:
    report = gate(counts={"unsupported_config": 1})
    assert report.status is WARN


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
    assert not [d for d in report.decisions if d.metric == "faithfulness" and d.dimension == "perturbed_all"]
    assert row(report.notable_slices, "faithfulness", "perturbation", "compound_split").notable
    assert report.status is PASS


def test_r16_invalid_inputs() -> None:
    cases, values = fixture_f0()
    base = make_run("base", cases, values)
    rng = np.random.default_rng

    def run(**kw: object) -> RunResults:
        return make_run("cand", cases, values, **kw)  # type: ignore[arg-type]

    with pytest.raises(GateInputError, match="fingerprint"):
        evaluate_gate(base, run(eval_fingerprint="other"), POLICY, rng(1), directions=DIRECTIONS)
    with pytest.raises(GateInputError, match="complete"):
        evaluate_gate(base, run(complete=False), POLICY, rng(1), directions=DIRECTIONS)
    with pytest.raises(GateInputError, match="complete"):
        evaluate_gate(make_run("base", cases, values, complete=False), run(), POLICY, rng(1), directions=DIRECTIONS)
    noisy = {**values, "error_rate": [1.0] * 6 + [0.0] * 114}
    with pytest.raises(GateInputError, match="error_rate"):
        evaluate_gate(make_run("base", cases, noisy), run(), POLICY, rng(1), directions=DIRECTIONS)
    missing = {k: v for k, v in DIRECTIONS.items() if k != "faithfulness"}
    with pytest.raises(GateInputError, match="faithfulness"):
        evaluate_gate(base, run(), POLICY, rng(1), directions=missing)


def test_absolute_values_must_be_binary() -> None:
    with pytest.raises(GateInputError, match="injection_success"):
        gate({"injection_success": {0: 0.5}})


def test_r17_testable_decisions_carry_p_and_mde() -> None:
    for report in (gate(), gate(everywhere("context_recall", 0.6))):
        for d in report.decisions:
            if d.status is INSUFFICIENT:
                assert d.p_adjusted is None and d.mde is None
                continue
            assert d.p_adjusted is not None and d.mde is not None and d.result is not None
            if d.result.se == 0:
                assert d.mde == pytest.approx(0.05)


def test_r19_thresholds_are_copied_from_the_policy() -> None:
    report = gate({**everywhere("context_recall", 0.6), "injection_success": {0: 1.0}})
    assert report.decisions
    assert all(d.max_drop == 0.05 and d.max_value is None for d in report.decisions)
    injection = [d for d in report.absolute_checks if d.metric == "injection_success"]
    assert injection
    assert all(d.max_value == 0.02 and d.max_drop is None for d in injection)


def test_r20_applicability_rule() -> None:
    idx = clusters(0, 34)
    na: Edits = {"context_recall": dict.fromkeys(idx, NA)}
    report = gate(na, base_edits=na)
    rows = [d for d in (*report.decisions, *report.notable_slices) if d.metric == "context_recall"]
    assert rows
    assert not [d for d in report.decisions if d.metric == "context_recall"]
    assert all(d.gated is False and d.informational_reason == "applicable_clusters<30" for d in rows)
    assert len([d for d in report.decisions if d.status is not INSUFFICIENT]) == 6
    assert report.not_applicable_counts["context_recall"] == 70


def test_r20_small_run_is_informational() -> None:
    cases = [make_case(i, cluster=i // 2) for i in range(20)]
    base = {m: [0.8] * 20 for m in DIRECTIONS}
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
    assert overall.result is not None and overall.result.n_cases == 116


def test_r22_tier1_gates_on_hard_fails_and_error_rate_only() -> None:
    informational = {m: "tier1_deterministic_only" for m in PAIRED}
    informational["injection_success"] = "tier1_injection_reported"
    edits: Edits = {**everywhere("language_match", 0.8), "injection_success": {2 * k: 1.0 for k in range(8)}}
    report = gate(edits, informational=informational)
    assert report.status is PASS
    injection = row(report.absolute_checks, "injection_success", "overall")
    assert injection.gated is False
    assert injection.status is PASS
    assert injection.informational_reason == "tier1_injection_reported"
    assert injection.notable is True
    errors: Edits = {**edits, "error_rate": dict.fromkeys(clusters(0, 11), 1.0)}
    assert gate(errors, informational=informational).status is FAIL


def test_r18_deterministic() -> None:
    first = gate(everywhere("context_recall", 0.6))
    second = gate(everywhere("context_recall", 0.6))
    assert first.model_dump_json() == second.model_dump_json()
    assert GateReport.model_validate_json(first.model_dump_json()) == first


def test_report_orders_and_counts() -> None:
    report = gate(everywhere("context_recall", 0.6))
    gated = [d for d in report.decisions]
    assert [d.metric for d in gated] == sorted(d.metric for d in gated)
    assert report.notable_slices
    flags = [d.notable for d in report.notable_slices]
    assert flags == sorted(flags, reverse=True)  # notable first


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
