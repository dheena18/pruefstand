"""Snapshots (syrupy) of the S5 scenarios; layout and copy per ui-spec §12."""

import pytest
from pruefstand.report.markdown import render_pr_comment
from syrupy.assertion import SnapshotAssertion
from testsupport.report_builders import (
    FAIL,
    INSUFFICIENT,
    PASS,
    WARN,
    Scenario,
    base_manifest,
    decision,
    gate_report,
    hard_fail,
    manifest,
    no_baseline_report,
    tier1_base,
    tier1_manifest,
    tier1_report,
)

from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import SliceDecision


def _info(metric: str, reason: str, base: float, cand: float) -> SliceDecision:
    return decision(
        metric,
        status=PASS,
        gated=False,
        base=base,
        cand=cand,
        ci=(cand - base, cand - base - 0.1, cand - base + 0.1),
        mde=None,
        max_drop=None,
        reason=reason,
    )


def _pass() -> Scenario:
    ok = decision(status=PASS, cand=0.85, ci=(-0.01, -0.03, 0.01))
    return (
        gate_report(status=PASS, hard_fails=(), decisions=(ok,), top_failing_cases=()),
        base_manifest(),
        manifest(),
    )


def _warn() -> Scenario:
    warn = decision(status=WARN, cand=0.80, ci=(-0.06, -0.1, -0.02))
    return (
        gate_report(status=WARN, hard_fails=(), decisions=(warn,), likely_cause="retrieval"),
        base_manifest(),
        manifest(),
    )


def _fail() -> Scenario:
    rows = (
        decision(cand=0.77, ci=(-0.09, -0.12, -0.06), mde=0.06),
        decision(
            "faithfulness", status=PASS, base=0.91, cand=0.90, ci=(-0.01, -0.03, 0.01), mde=0.07
        ),
        decision(
            dimension="tenant",
            value="kanzlei_mueller",
            status=WARN,
            base=0.84,
            cand=0.77,
            ci=(-0.07, -0.11, -0.03),
            mde=0.10,
        ),
    )
    absolute = decision(
        "injection_success",
        status=WARN,
        base=0.0,
        cand=0.03,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    notable = (
        decision(
            dimension="perturbation",
            value="compound_split",
            status=PASS,
            gated=False,
            notable=True,
            ci=(-0.18, -0.3, -0.05),
            mde=None,
            max_drop=None,
        ),
        decision(
            dimension="category",
            value="cross_lingual",
            status=PASS,
            gated=False,
            notable=True,
            ci=(-0.09, -0.2, 0.0),
            mde=None,
            max_drop=None,
        ),
        _info("answer_correctness", "judge_drift", 0.80, 0.78),
    )
    thin = decision(dimension="tenant", value="stadtwerke_sued", status=INSUFFICIENT, n_clusters=22)
    report = gate_report(
        decisions=(*rows, thin),
        absolute_checks=(absolute,),
        notable_slices=notable,
        likely_cause="retrieval",
        not_applicable_counts={"answer_correctness": 12},
        top_failing_cases=(CaseId("law-0042"), CaseId("law-0107"), CaseId("xl-0013")),
    )
    return report, base_manifest(), manifest(judge_drift=True)


def _hard_fail() -> Scenario:
    return gate_report(), base_manifest(), manifest()


def _insufficient() -> Scenario:
    thin = decision(status=INSUFFICIENT, n_clusters=12)
    return (
        gate_report(status=INSUFFICIENT, hard_fails=(), decisions=(thin,)),
        base_manifest(),
        manifest(),
    )


def _notable_only() -> Scenario:
    notable = decision(
        dimension="perturbation",
        value="compound_split",
        status=PASS,
        gated=False,
        notable=True,
        ci=(-0.18, -0.3, -0.05),
        mde=None,
        max_drop=None,
    )
    ok = decision(status=PASS, cand=0.86, ci=(0.0, -0.02, 0.02))
    return (
        gate_report(status=PASS, hard_fails=(), decisions=(ok,), notable_slices=(notable,)),
        base_manifest(),
        manifest(),
    )


def _judge_notices() -> Scenario:
    rows = (
        _info("faithfulness", "judge_degraded", 0.9, 0.85),
        _info("answer_correctness", "judge_drift", 0.8, 0.78),
    )
    ok = decision(status=PASS, cand=0.86, ci=(0.0, -0.02, 0.02))
    report = gate_report(status=PASS, hard_fails=(), decisions=(ok,), notable_slices=rows)
    cand = manifest(judge_fallback=True, judge_degraded=True, judge_drift=True)
    return report, base_manifest(), cand


def _no_baseline() -> Scenario:
    return no_baseline_report(), None, manifest()


def _truncated() -> Scenario:
    rows = tuple(
        decision(dimension="tags", value=f"tag-{i:04d}", status=WARN, ci=(-0.1, -0.2, -0.05))
        for i in range(3_000)
    )
    return gate_report(decisions=(decision(), *rows)), base_manifest(), manifest()


def _nightly_block() -> Scenario:
    ok = decision(status=PASS, cand=0.86, ci=(0.0, -0.02, 0.02))
    report = gate_report(status=PASS, hard_fails=(), decisions=(ok,))
    return (
        report,
        base_manifest(splits=["full"], block=1, workload="nightly"),
        manifest(splits=["full"], block=1, workload="nightly", n_cases=1500),
    )


def _judged_subset() -> Scenario:
    ok = decision(status=PASS, cand=0.86, ci=(0.0, -0.02, 0.02))
    row = _info("answer_correctness", "judge_uncalibrated", 0.8, 0.79)
    report = gate_report(status=PASS, hard_fails=(), decisions=(ok,), notable_slices=(row,))
    return report, base_manifest(), manifest(judged_subset=True)


def _t1_pass() -> Scenario:
    return tier1_report(), tier1_base(), tier1_manifest()


def _t1_skipped() -> Scenario:
    rows = tier1_report().notable_slices
    report = tier1_report(
        notable_slices=tuple(r for r in rows if r.informational_reason != "tier1_judged")
    )
    return report, tier1_base(), tier1_manifest(judge_mode="skipped", judged_cases=0)


def _t1_hard_fail() -> Scenario:
    report = tier1_report(status=FAIL, hard_fails=(hard_fail("law-0042", "tenant_leak"),))
    return report, tier1_base(), tier1_manifest()


def _t1_no_baseline() -> Scenario:
    return no_baseline_report(), None, tier1_manifest()


SCENARIOS = {
    "t2_pass": _pass,
    "t2_warn": _warn,
    "t2_fail": _fail,
    "t2_hard_fail": _hard_fail,
    "t2_insufficient": _insufficient,
    "t2_notable_only": _notable_only,
    "t2_judge_notices": _judge_notices,
    "t2_no_baseline": _no_baseline,
    "t2_truncated": _truncated,
    "t2_nightly_block": _nightly_block,
    "t2_judged_subset": _judged_subset,
    "t1_pass": _t1_pass,
    "t1_judge_skipped": _t1_skipped,
    "t1_hard_fail": _t1_hard_fail,
    "t1_no_baseline": _t1_no_baseline,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_snapshot(name: str, snapshot: SnapshotAssertion) -> None:
    report, base, cand = SCENARIOS[name]()
    out = render_pr_comment(report, base, cand, report_url="https://example.org/runs/1")
    assert out == snapshot
    assert "run-gate" not in out
