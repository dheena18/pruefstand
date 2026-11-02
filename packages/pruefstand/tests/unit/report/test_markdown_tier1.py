"""Tier-1 PR comment (ui-spec §12.2, X5.6, X3.11): hard fails and the error rate decide."""

from testsupport.report_builders import (
    FAIL,
    PASS,
    decision,
    gate_report,
    hard_fail,
    manifest,
    no_baseline_report,
    tier1_base,
    tier1_manifest,
    tier1_report,
)

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.report.markdown import render_pr_comment

SKIPPED = (
    "> ℹ️ Judge skipped (quota used up). Judged metrics are not shown; "
    "the deterministic gate still decided."
)


def render(report: GateReport | None = None, cand: RunManifest | None = None) -> str:
    return render_pr_comment(
        report or tier1_report(),
        tier1_base(),
        cand or tier1_manifest(),
        report_url="https://example.org/r",
    )


def test_pass_layout() -> None:
    lines = render().splitlines()
    assert lines[1] == "## Prüfstand tier 1: ✅ PASS (0 blocking issues)"
    assert lines[2] == (
        "Baseline: main@a1b2c3d · Candidate: pr-42@d4e5f6a · smoke_live · 20 cases · "
        "14m 03s · 0 USD · 200 k tokens"
    )
    assert lines[3].startswith(
        "> ℹ️ Tier 1 decides on hard fails and the error rate only. "
        "Language, citation, refusal and injection results are reported."
    )
    assert "GPU-s" not in "\n".join(lines)


def test_check_table_rows() -> None:
    out = render()
    assert "| Check | Value | Max | Status |" in out
    assert "| Hard fails (canary, tenant, system prompt) | 0 | 0 | PASS |" in out
    assert "| Error rate | 0.00 | 0.02 | PASS |" in out


def test_reported_table_in_details_without_ci_or_status_word() -> None:
    out = render()
    start = out.index("<details><summary>Reported, does not decide at n = 20 (4)</summary>")
    block = out[start : out.index("</details>", start)]
    assert "| Metric | Base | PR | Δ | MDE | Max | Reported because |" in block
    assert "| Language match | 1.00 | 0.95 | −0.05 | 0.21 | – | reported in tier 1 |" in block
    assert "| False refusal | 0.00 | 0.00 | +0.00 | – | – | reported in tier 1 |" in block
    assert (
        "| Injection success | 0.00 | 0.00 | – | – | 0.02 | injection reported in tier 1 |" in block
    )
    for word in ("PASS", "WARN", "FAIL", "("):
        assert word not in block.split("\n\n", 1)[1].replace("<details", "")


def test_informational_and_judged_lines() -> None:
    out = render()
    assert (
        "Informational (does not block): Refusal correct 1.00 → 1.00 (+0.00) — "
        "refusal gated only in nightly full" in out
    )
    assert (
        "**Judged metrics (informational, does not block; GitHub Models, 10 cases):** "
        "Faithfulness 0.88 → 0.85 (−0.03) · Answer correctness 0.91 → 0.90 (−0.01)"
    ) in out
    assert "Top failing cases: law-0042" in out
    assert "statistical gate: tier 2</sub>" in out


def test_judged_source_label_local_and_subset() -> None:
    out = render(cand=tier1_manifest(judge_mode="local", judged_subset=True, judged_cases=150))
    assert "local judge (A40), 150 cases" in out
    assert "judged subset (150 cases)" in out


def test_judge_skipped_line_replaces_judged_numbers() -> None:
    out = render(cand=tier1_manifest(judge_mode="skipped", judged_cases=0))
    assert SKIPPED in out.splitlines()
    assert out.count(SKIPPED) == 1
    assert "Judged metrics (" not in out
    assert "Faithfulness" not in out


def test_hard_fail_comes_first_and_check_row_counts() -> None:
    report = tier1_report(status=FAIL, hard_fails=(hard_fail("law-0001", "tenant_leak"),))
    out = render(report)
    assert "## Prüfstand tier 1: ❌ FAIL (1 blocking issue)" in out
    assert out.index("### 🚨 Hard fails (1)") < out.index("| Check |")
    assert "| Hard fails (canary, tenant, system prompt) | 1 | 0 | FAIL |" in out


def test_gated_error_rate_fail_blocks() -> None:
    bad = decision(
        "error_rate",
        status=FAIL,
        base=0.0,
        cand=0.1,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    out = render(tier1_report(status=FAIL, absolute_checks=(bad,)))
    assert "(1 blocking issue)" in out
    assert "| Error rate | 0.10 | 0.02 | FAIL |" in out


def test_no_baseline() -> None:
    out = render_pr_comment(no_baseline_report(), None, tier1_manifest(), report_url=None)
    assert out.splitlines()[1] == "## Prüfstand tier 1: ⚪ NO BASELINE (nothing compared)"
    assert "Baseline: –" in out
    assert "No baseline for" in out
    assert "| Check |" not in out
    assert "✅" not in out


def test_no_judged_metric_is_ever_warn_or_fail() -> None:
    out = render()
    for line in out.splitlines():
        if "Faithfulness" in line or "Answer correctness" in line:
            assert "WARN" not in line
            assert "FAIL" not in line


def test_judge_flags_notices_in_tier1() -> None:
    out = render(cand=tier1_manifest(judge_drift=True, judge_fallback=True))
    notices = [ln for ln in out.splitlines() if ln.startswith("> ") and "Tier 1 decides" not in ln]
    assert notices[0].startswith("> ⚠️ Some judgments came from the fallback judge")
    assert notices[1].startswith("> ⚠️ Judge drift detected (5 or more of 50")


def test_tier2_manifest_makes_tier2_layout() -> None:
    out = render_pr_comment(gate_report(), tier1_base(stack="a40"), manifest(), report_url=None)
    assert "Prüfstand tier 1" not in out
    assert PASS
