"""Snapshots (syrupy) of the HTML report scenarios; CSS and script are replaced by a marker."""

import re

import pytest
from syrupy.assertion import SnapshotAssertion
from testsupport.html_builders import run_of
from testsupport.report_builders import (
    PASS,
    WARN,
    absolute_row,
    base_manifest,
    decision,
    gate_report,
    manifest,
    no_baseline_report,
    notable_row,
    tier1_base,
    tier1_manifest,
    tier1_report,
)

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.report.html import render_html

Scenario = tuple[GateReport, RunResults | None, RunResults]


def stripped(text: str) -> str:
    text = re.sub(r"<style>.*?</style>", "<style>…</style>", text, flags=re.S)
    text = re.sub(r"<script>.*?</script>", "<script>…</script>", text, flags=re.S)
    return re.sub(r"sha256-[A-Za-z0-9+/=]+", "sha256-HASH", text)


def _fail() -> Scenario:
    rows = (
        decision(cand=0.77, ci=(-0.09, -0.12, -0.06), mde=0.06),
        decision(
            dimension="tenant",
            value="kanzlei_mueller",
            status=WARN,
            cand=0.77,
            ci=(-0.07, -0.11, -0.03),
        ),
    )
    report = gate_report(
        decisions=rows,
        absolute_checks=(absolute_row("injection_success", 0.03, WARN),),
        notable_slices=(notable_row("perturbation", "compound_split", -0.18),),
        likely_cause="retrieval",
    )
    return report, run_of(base_manifest()), run_of(manifest())


def _pass() -> Scenario:
    report = gate_report(
        status=PASS,
        hard_fails=(),
        decisions=(decision(status=PASS, cand=0.85),),
        top_failing_cases=(),
    )
    return report, run_of(base_manifest()), run_of(manifest())


def _tier1() -> Scenario:
    return tier1_report(), run_of(tier1_base()), run_of(tier1_manifest(judge_mode="github"))


def _tier1_skipped() -> Scenario:
    return tier1_report(), run_of(tier1_base()), run_of(tier1_manifest(judge_mode="skipped"))


def _no_baseline() -> Scenario:
    return no_baseline_report(), None, run_of(manifest())


SCENARIOS = {
    "tier2_fail_hard_fail": _fail,
    "tier2_pass": _pass,
    "tier1_pass": _tier1,
    "tier1_judge_skipped": _tier1_skipped,
    "no_baseline": _no_baseline,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_html_snapshot(name: str, snapshot: SnapshotAssertion) -> None:
    report, base, cand = SCENARIOS[name]()
    assert stripped(render_html(report, base, cand)) == snapshot
