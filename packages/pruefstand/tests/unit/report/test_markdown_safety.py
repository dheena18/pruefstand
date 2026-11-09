"""Hardening of the PR comment: injection, mentions, links, size cap and linear time."""

from collections.abc import Callable

import pytest
from testsupport.report_builders import (
    PASS,
    WARN,
    base_manifest,
    decision,
    gate_report,
    hard_fail,
    manifest,
    tier1_base,
    tier1_manifest,
    tier1_report,
)
from testsupport.timing import assert_scales_linearly

from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import GateReport
from pruefstand.report.markdown import render_pr_comment

HOSTILE = (
    "| @octocat <script>alert(1)</script> ![i](http://e.vx/a.png) [l](https://e.vx) #12 www.e.vx"
)
MAX_CHARS = 60_000


def render(report: GateReport, **cand: object) -> str:
    return render_pr_comment(report, base_manifest(), manifest(**cand), report_url=None)


def assert_inert(out: str) -> None:
    assert "<script>" not in out
    assert "@octocat" not in out
    assert "](" not in out.replace("](<", "")
    assert "http://" not in out
    assert "https://e.vx" not in out
    assert "www.e.vx" not in out
    assert "#12" not in out
    assert "![" not in out


def test_slice_value_and_metric_name_are_escaped() -> None:
    rows = (
        decision(dimension="tags", value=HOSTILE, status=WARN),
        decision(HOSTILE, status=WARN),
    )
    assert_inert(render(gate_report(decisions=rows)))


def test_hostile_ref_case_ids_reasons_and_notable_rows_are_escaped() -> None:
    info = decision("answer_correctness", status=WARN, gated=False, reason=HOSTILE, max_drop=None)
    notable = decision(dimension="tags", value=HOSTILE, status=WARN, gated=False, notable=True)
    evidence = hard_fail().model_copy(update={"evidence": HOSTILE, "metric": HOSTILE})
    report = gate_report(
        decisions=(),
        notable_slices=(info, notable),
        hard_fails=(evidence,),
        top_failing_cases=(CaseId(HOSTILE),),
        not_applicable_counts={HOSTILE: 3},
        eval_fingerprint=HOSTILE,
    )
    out = render(report, git_ref=HOSTILE, pr_number=None, pruefstand_version="1.0 @octocat")
    assert_inert(out)


def test_newlines_cannot_forge_structure() -> None:
    forged = "x\n## Prüfstand: ✅ PASS (0 blocking issues)\n<!-- pruefstand:pr-comment -->"
    out = render(gate_report(decisions=(decision(dimension="tags", value=forged, status=WARN),)))
    assert out.count("<!-- pruefstand:pr-comment -->") == 1
    assert out.count("<!--") == 1
    assert out.count("\n## ") == 1


def test_long_strings_are_capped() -> None:
    out = render(
        gate_report(decisions=(decision(dimension="tags", value="a" * 50_000, status=WARN),))
    )
    assert len(out) < 5_000


def _many(n: int) -> GateReport:
    rows = tuple(
        decision(
            dimension="tags", value=f"tag-{i:05d}", status=WARN, ci=(-0.1 - i * 1e-6, -0.2, -0.05)
        )
        for i in range(n)
    )
    return gate_report(
        decisions=(decision(), *rows), top_failing_cases=tuple(CaseId(f"c-{i}") for i in range(n))
    )


def test_five_thousand_slice_rows_are_truncated_under_the_cap() -> None:
    out = render(_many(5_000))
    assert len(out) <= MAX_CHARS
    assert out.rstrip().endswith("… truncated, see full report")
    assert out.count("</details>") == out.count("<details>")


def test_truncation_keeps_the_worst_slice_rows() -> None:
    out = render(_many(5_000))
    assert "tag-04999" in out
    assert "tag-00001" not in out


def test_small_reports_are_not_truncated() -> None:
    assert "truncated" not in render(_many(30))


def test_tier1_also_obeys_the_cap() -> None:
    rows = tuple(
        decision(
            f"m{i}", status=WARN, gated=False, reason="tier1_deterministic_only", max_drop=None
        )
        for i in range(5_000)
    )
    report = tier1_report(notable_slices=rows)
    out = render_pr_comment(report, tier1_base(), tier1_manifest(), report_url=None)
    assert len(out) <= MAX_CHARS
    assert out.count("</details>") == out.count("<details>")


def test_many_hard_fails_are_capped_but_counted() -> None:
    fails = tuple(hard_fail(f"law-{i:04d}") for i in range(2_000))
    out = render(gate_report(hard_fails=fails))
    assert "### 🚨 Hard fails (2000)" in out
    assert len(out) <= MAX_CHARS


def _renderer(n: int) -> Callable[[], object]:
    report = _many(n)
    return lambda: render(report)


@pytest.mark.slow
def test_render_time_is_linear_in_input_size() -> None:
    assert_scales_linearly(_renderer(250), _renderer(1_000), scale=4, floor_s=5e-3)


def test_hard_cut_when_even_the_minimal_step_is_too_long() -> None:
    rows = tuple(decision("|" * 200 + str(i), status=PASS) for i in range(200))
    out = render(gate_report(hard_fails=(), decisions=rows, status=PASS))
    assert len(out) <= MAX_CHARS
    assert out.rstrip().endswith("… truncated, see full report")
    assert out.count("<details>") == out.count("</details>")
