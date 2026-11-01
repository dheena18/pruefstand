"""``evaluate_gate`` (T1.7, R1-R11, R13, R16-R18): statuses, hard fails, errors, validation."""

import numpy as np
import pytest
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import (
    DIRECTIONS,
    FAIL,
    INSUFFICIENT,
    PAIRED,
    PASS,
    POLICY,
    WARN,
    Edits,
    clusters,
    everywhere,
    gate,
    row,
)

from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.gate.policy import evaluate_gate


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
    assert [(h.rule, h.case_id, h.metric) for h in report.hard_fails] == [
        ("hard_fail", "c0005", metric)
    ]
    assert report.likely_cause is None


def test_r11_errors_dominate() -> None:
    idx = clusters(0, 11)
    edits: Edits = {
        **{m: dict.fromkeys(idx, None) for m in DIRECTIONS if m != "error_rate"},
        "error_rate": dict.fromkeys(idx, 1.0),
    }
    report = gate(edits)
    rate = row(report.absolute_checks, "error_rate", "overall")
    assert rate.gated
    assert rate.status is FAIL
    assert rate.candidate_mean == pytest.approx(24 / 120)
    recall = row(report.decisions, "context_recall", "overall")
    assert recall.result is not None
    assert recall.result.mean_diff == pytest.approx(-0.16)
    assert recall.status is FAIL
    assert report.status is FAIL
    assert report.likely_cause == "errors"


def test_r13_unsupported_config_warns() -> None:
    report = gate(counts={"unsupported_config": 1})
    assert report.status is WARN


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
        evaluate_gate(
            make_run("base", cases, values, complete=False),
            run(),
            POLICY,
            rng(1),
            directions=DIRECTIONS,
        )
    noisy_column: list[float | None] = [*([1.0] * 6), *([0.0] * 114)]
    noisy = {**values, "error_rate": noisy_column}
    with pytest.raises(GateInputError, match="error_rate"):
        evaluate_gate(make_run("base", cases, noisy), run(), POLICY, rng(1), directions=DIRECTIONS)
    missing = {k: v for k, v in DIRECTIONS.items() if k != "faithfulness"}
    with pytest.raises(GateInputError, match="faithfulness"):
        evaluate_gate(base, run(), POLICY, rng(1), directions=missing)


def test_r17_testable_decisions_carry_p_and_mde() -> None:
    for report in (gate(), gate(everywhere("context_recall", 0.6))):
        for d in report.decisions:
            if d.status is INSUFFICIENT:
                assert d.p_adjusted is None
                assert d.mde is None
                continue
            assert d.p_adjusted is not None
            assert d.mde is not None
            assert d.result is not None
            if d.result.se == 0:
                assert d.mde == pytest.approx(0.05)


def test_r18_deterministic() -> None:
    first = gate(everywhere("context_recall", 0.6))
    second = gate(everywhere("context_recall", 0.6))
    assert first.model_dump_json() == second.model_dump_json()
    assert GateReport.model_validate_json(first.model_dump_json()) == first


def test_report_orders_and_counts() -> None:
    report = gate(everywhere("context_recall", 0.6))
    gated = list(report.decisions)
    assert [d.metric for d in gated] == sorted(d.metric for d in gated)
    assert report.notable_slices
    flags = [d.notable for d in report.notable_slices]
    assert flags == sorted(flags, reverse=True)  # notable first
