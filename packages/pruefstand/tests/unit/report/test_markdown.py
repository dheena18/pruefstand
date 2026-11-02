"""Tier-2 PR comment (ui-spec §12.1): header, tables and single-line sections."""

import pytest
from testsupport.report_builders import (
    FAIL,
    INSUFFICIENT,
    PASS,
    WARN,
    decision,
    gate_report,
    hard_fail,
)
from testsupport.report_render import MARKER, ROW, line_with, render

from pruefstand.core.enums import GateStatus


def test_fail_report_header_row_and_refs() -> None:
    out = render()
    lines = out.splitlines()
    assert lines[0] == MARKER
    assert lines[1] == "## Prüfstand: ❌ FAIL (2 blocking issues)"
    assert lines[2] == (
        "Baseline: main@a1b2c3d · Candidate: pr-42@d4e5f6a · core, robust_pr · 790 cases · "
        "18m 12s · 0 USD · 4.1 M tokens · ~2,100 GPU-s"
    )
    assert ROW in lines
    assert "| Metric | Base | PR | Δ (95% CI) | δ | MDE | Status |" in lines
    assert out.endswith("\n")


def test_blocking_count_is_hard_fails_plus_gated_fails() -> None:
    absolute = decision(
        "injection_success",
        status=FAIL,
        base=0.0,
        cand=0.05,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    slice_fail = decision(dimension="tenant", value="a", status=FAIL)
    report = gate_report(decisions=(decision(), slice_fail), absolute_checks=(absolute,))
    assert "## Prüfstand: ❌ FAIL (4 blocking issues)" in render(report)
    single = gate_report(hard_fails=(), decisions=(decision(),))
    assert "(1 blocking issue)" in render(single)


@pytest.mark.parametrize(
    ("status", "title"),
    [
        (PASS, "## Prüfstand: ✅ PASS (0 blocking issues)"),
        (WARN, "## Prüfstand: ⚠️ WARN (0 blocking issues)"),
        (INSUFFICIENT, "## Prüfstand: ◌ INSUFFICIENT DATA (0 blocking issues)"),
    ],
)
def test_titles(status: GateStatus, title: str) -> None:
    report = gate_report(status=status, hard_fails=(), decisions=(decision(status=status),))
    assert render(report).splitlines()[1] == title


def test_unsupported_config_counts_as_warn() -> None:
    report = gate_report(status=GateStatus.UNSUPPORTED_CONFIG, hard_fails=(), decisions=())
    out = render(report)
    assert "⚠️ WARN" in out
    assert "> ⚠️ Unsupported configuration — counted as WARN." in out


def test_delta_column_is_max_drop_and_dash_when_none() -> None:
    row = decision(max_drop=None, mde=None)
    out = render(gate_report(hard_fails=(), decisions=(row,)))
    assert "| Context recall | 0.86 | 0.79 | −0.07 (−0.10, −0.04) | – | – | FAIL |" in out


def test_absolute_checks_line_lists_non_pass_rows_and_max() -> None:
    bad = decision(
        "injection_success",
        status=WARN,
        base=0.0,
        cand=0.03,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    ok = decision(
        "error_rate",
        status=PASS,
        base=0.0,
        cand=0.0,
        ci=None,
        mde=None,
        max_drop=None,
        max_value=0.02,
    )
    out = render(gate_report(hard_fails=(), absolute_checks=(bad, ok)))
    assert "Absolute checks: Injection success 0.03 (max 0.02) WARN" in out
    assert "Error rate" not in out


def test_absolute_checks_all_pass_line() -> None:
    rows = tuple(
        decision(
            m, status=PASS, base=0.0, cand=0.0, ci=None, mde=None, max_drop=None, max_value=0.02
        )
        for m in ("injection_success", "error_rate")
    )
    out = render(gate_report(hard_fails=(), decisions=(), absolute_checks=rows, status=PASS))
    assert "Absolute checks: all PASS (2)" in out


def test_notable_line_only_notable_rows() -> None:
    hit = decision(
        dimension="perturbation",
        value="compound_split",
        status=PASS,
        gated=False,
        notable=True,
        ci=(-0.18, -0.3, -0.05),
        mde=None,
        max_drop=None,
    )
    miss = decision(
        dimension="category",
        value="quiet",
        status=PASS,
        gated=False,
        notable=False,
        ci=(-0.01, -0.1, 0.1),
        mde=None,
        max_drop=None,
    )
    out = render(gate_report(notable_slices=(hit, miss)))
    line = line_with(out, "Notable slice drops (informational):")
    assert line == "Notable slice drops (informational): perturbation=compound_split −0.18"
    assert out.count("compound_split") == 1
    assert "quiet" not in out


def test_likely_cause_line() -> None:
    out = render(gate_report(likely_cause="retrieval"))
    assert (
        "Likely cause: retrieval — Retrieval "
        "(chunking, embeddings, top-k, reranker, filter, analyzer)" in out
    )
    assert "<codes>" not in render(gate_report(likely_cause="mixed"))


def test_not_applicable_and_insufficient_lines() -> None:
    thin = decision(dimension="tenant", value="stadtwerke_sued", status=INSUFFICIENT, n_clusters=22)
    out = render(
        gate_report(not_applicable_counts={"answer_correctness": 12}, decisions=(decision(), thin))
    )
    assert (
        "Not applicable: answer_correctness (12 cases) · "
        "Insufficient data: Context recall · tenant=stadtwerke_sued (22 clusters)"
    ) in out
    assert "Not applicable" not in render(gate_report(not_applicable_counts={}))
    assert "Insufficient data" not in render()


def test_gated_slices_not_passing_in_details() -> None:
    warn = decision(
        dimension="tenant",
        value="kanzlei_mueller",
        status=WARN,
        ci=(-0.07, -0.11, -0.03),
        mde=0.10,
        base=0.84,
        cand=0.77,
    )
    passing = decision(dimension="tenant", value="quiet", status=PASS)
    perturbed = decision(dimension="perturbed_all", value="perturbed_all", status=FAIL)
    out = render(gate_report(decisions=(decision(), warn, passing, perturbed)))
    assert "<details><summary>Gated slices not passing (2)</summary>" in out
    assert (
        "| tenant=kanzlei_mueller | Context recall | 0.84 | 0.77 | "
        "−0.07 (−0.11, −0.03) | 0.05 | 0.10 | WARN |" in out
    )
    assert "perturbed_all=perturbed_all" in out
    assert "quiet" not in out
    assert out.count("</details>") == 1


def test_section_with_more_than_five_rows_is_collapsed() -> None:
    names = [
        "context_recall",
        "faithfulness",
        "citation_recall",
        "language_match",
        "citation_precision",
        "ndcg_at_k",
    ]
    rows = tuple(decision(n, status=PASS) for n in names)
    out = render(gate_report(hard_fails=(), decisions=rows, status=PASS))
    assert out.index("<details><summary>") < out.index("nDCG@k") < out.index("</details>")
    out5 = render(gate_report(hard_fails=(), decisions=rows[:5], status=PASS))
    assert "<details>" not in out5


def test_hard_fail_section_first_and_masked() -> None:
    leaked = hard_fail().model_copy(update={"evidence": "… CANARY-VN-7f3a9c Bergmann …"})
    out = render(gate_report(hard_fails=(leaked,)))
    assert out.index("### 🚨 Hard fails (1)") < out.index("| Metric |")
    assert "| Rule | Case | Metric | Evidence (redacted) |" in out
    assert "| canary_leak | law-0107 | canary_leak | `… CANARY-**-****** Bergmann …` |" in out
    assert "7f3a9c" not in out
    assert "CANARY-VN" not in out


def test_comment_never_contains_chunk_text() -> None:
    out = render()
    assert "Arbeitsvertrag Bergmann" not in out


def test_report_url_present_and_absent() -> None:
    assert "[Full report](<https://example.org/r/1>)" in render()
    out = render(url=None)
    assert "Full report" not in out
    assert "(full report in the private executor run)" in out
    assert "javascript" not in render(url="javascript:alert(1)")
    assert "Full report" not in render(url="javascript:alert(1)")


def test_footer_mentions_fail_on_warn() -> None:
    assert "WARN does not block unless --fail-on-warn</sub>" in render()
