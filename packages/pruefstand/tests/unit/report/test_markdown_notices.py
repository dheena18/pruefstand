"""Tier-2 PR comment: judge notices, informational rows, block, no-baseline states."""

from testsupport.report_builders import (
    BASE_SHA,
    PASS,
    decision,
    gate_report,
    hard_fail,
    info_row,
    manifest,
    no_baseline_report,
)
from testsupport.report_render import DRIFT, ROW, line_with, render

from pruefstand.report.markdown import render_pr_comment


def test_judge_notices_in_order_and_only_when_true() -> None:
    cand = manifest(
        judge_mode="skipped", judge_fallback=True, judge_degraded=True, judge_drift=True
    )
    notices = [ln for ln in render(cand=cand).splitlines() if ln.startswith("> ")]
    assert notices == [
        "> ℹ️ Judge skipped (quota used up). Judged metrics are not shown; "
        "the deterministic gate still decided.",
        "> ⚠️ Some judgments came from the fallback judge; judged metrics are informational.",
        "> ⚠️ The judge failed on more than 5 % of cases; judged metrics are informational.",
        DRIFT,
    ]
    assert not [ln for ln in render().splitlines() if ln.startswith("> ")]


def test_drift_text_is_the_count_rule() -> None:
    out = render(cand=manifest(judge_drift=True))
    assert DRIFT in out.splitlines()
    for line in (ln for ln in out.splitlines() if ln.startswith(">")):
        assert "0.85" not in line
        assert "recalibration" not in line


def test_informational_row_with_reason_never_in_gated_table() -> None:
    row = decision(
        "answer_correctness",
        status=PASS,
        gated=False,
        base=0.80,
        cand=0.78,
        ci=(-0.02, -0.1, 0.05),
        mde=None,
        max_drop=None,
        reason="judge_drift",
    )
    out = render(gate_report(notable_slices=(row,)))
    assert (
        "Informational (does not block): Answer correctness 0.80 → 0.78 (−0.02) — judge drift"
        in out
    )
    assert out.count("Answer correctness") == 1
    assert "| Answer correctness" not in out


def test_block_on_the_refs_line() -> None:
    cand = manifest(splits=["full"], block=1)
    assert "· full block 1 ·" in render(cand=cand).splitlines()[2]
    assert "block" not in render(cand=manifest(splits=["full"])).splitlines()[2]


def test_judged_subset_caption() -> None:
    row = decision(
        "answer_correctness",
        status=PASS,
        gated=False,
        base=0.8,
        cand=0.78,
        ci=(-0.02, -0.1, 0.05),
        mde=None,
        max_drop=None,
        reason="judge_uncalibrated",
    )
    report = gate_report(notable_slices=(row,))
    assert "judged subset (150 cases)" in render(report, cand=manifest(judged_subset=True))
    assert "judged subset" not in render(report, cand=manifest(judged_subset=False))


def test_judge_truncation_count_and_reason_label() -> None:
    row = decision(
        "faithfulness",
        status=PASS,
        gated=False,
        base=0.9,
        cand=0.8,
        ci=(-0.1, -0.2, 0.0),
        mde=None,
        max_drop=None,
        reason="judge_truncated",
    )
    out = render(
        gate_report(notable_slices=(row,)), cand=manifest(counts={"ok": 2, "judge_truncated": 2})
    )
    assert "— judge input truncated" in out
    assert "Judge input truncated on 2 cases" in out
    assert "truncated on" not in render()


def test_no_baseline_comment() -> None:
    cand = manifest()
    out = render_pr_comment(no_baseline_report(), None, cand, report_url=None)
    lines = out.splitlines()
    assert lines[1] == "## Prüfstand: ⚪ NO BASELINE (nothing compared)"
    assert lines[2].startswith("Baseline: – · Candidate: pr-42@d4e5f6a")
    assert f"> ❌ No baseline for {'e' * 16}; run baseline-promote. Nothing was compared." in out
    assert "| Metric |" not in out
    assert "✅" not in out


def test_no_baseline_still_lists_hard_fails() -> None:
    report = no_baseline_report(hard_fails=(hard_fail(),))
    out = render_pr_comment(report, None, manifest(), report_url=None)
    assert "### 🚨 Hard fails (1)" in out


def test_base_none_with_baseline_id_shows_the_id_and_keeps_base_from_decisions() -> None:
    out = render_pr_comment(gate_report(), None, manifest(), report_url=None)
    assert "Baseline: `20261101T220000-ba5e00` · Candidate:" in out
    assert ROW in out


def test_no_label_instruction_anywhere() -> None:
    for report in (gate_report(), no_baseline_report()):
        assert "run-gate" not in render(report)


def test_no_gpu_without_a40_and_no_secret_like_text() -> None:
    out = render(cand=manifest(stack="live"))
    assert "GPU-s" not in out
    assert BASE_SHA not in out


def test_reasonless_absolute_slice_rows_do_not_crowd_the_informational_line() -> None:
    slices = [f"s{i}" for i in range(7)]
    noise = tuple(
        decision(
            m,
            dimension="tenant",
            value=v,
            status=PASS,
            gated=False,
            base=0.0,
            cand=0.0,
            ci=None,
            mde=None,
            max_drop=None,
            max_value=0.02,
        )
        for m in ("error_rate", "injection_success")
        for v in slices
    )
    small = tuple(
        info_row("citation_f1", "applicable_clusters<30", 0.9, 0.9, diff=0.0) for _ in range(12)
    )
    drift = info_row("faithfulness", "judge_drift", 0.9, 0.8, diff=-0.1)
    loud = decision(
        "error_rate",
        dimension="lang",
        value="loud",
        status=PASS,
        gated=False,
        notable=True,
        base=0.0,
        cand=0.05,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    report = gate_report(
        hard_fails=(), decisions=(), absolute_checks=(*noise, loud), notable_slices=(*small, drift)
    )
    out = render(report)
    line = line_with(out, "Informational (does not block):")
    assert "Faithfulness 0.90 → 0.80 (−0.10) — judge drift" in line
    assert "and" not in line.split("judge drift")[-1]
    assert "— –" not in line
    assert "tenant=s0" not in out
    assert "lang=loud" in line_with(out, "Notable slice drops (informational):")
