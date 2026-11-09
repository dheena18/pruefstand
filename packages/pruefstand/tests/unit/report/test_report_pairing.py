"""T1.9a: ``n_unmatched`` / ``n_excluded`` and the judge-truncation case ids in the reports."""

from syrupy.assertion import SnapshotAssertion
from testsupport.html_builders import run_of
from testsupport.report_builders import base_manifest, gate_report, manifest
from testsupport.report_render import line_with, render

from pruefstand.report.html import render_html
from pruefstand.report.markdown import render_pr_comment
from pruefstand.report.truncation import judge_truncated_case_ids

PAIRED = {
    "n_unmatched": {"faithfulness": 3},
    "n_excluded": {"faithfulness": 2, "answer_relevancy": 1},
}
CUT = manifest(counts={"ok": 2, "judge_truncated": 2})


def test_pairing_line_lists_unmatched_and_excluded_per_metric() -> None:
    out = render(gate_report(**PAIRED))
    assert line_with(out, "Not paired:") == (
        "Not paired: answer_relevancy (1 excluded) · faithfulness (3 in one run only, 2 excluded)"
    )


def test_no_pairing_line_without_dropped_cases() -> None:
    assert "Not paired" not in render()


def test_truncated_case_ids_are_listed_escaped_and_capped() -> None:
    ids = ["law-0042", "law-0107", "a|b"]
    out = render_pr_comment(
        gate_report(), base_manifest(), CUT, report_url=None, truncated_cases=ids
    )
    assert "Judge input truncated on 2 cases" in out
    assert line_with(out, "Truncated cases:") == r"Truncated cases: law-0042, law-0107, a\|b"
    many = [f"law-{i:04d}" for i in range(80)]
    capped = render_pr_comment(
        gate_report(), base_manifest(), CUT, report_url=None, truncated_cases=many
    )
    assert "law-0049" in capped
    assert "law-0050" not in capped


def test_no_ids_line_when_nothing_was_truncated_or_ids_not_given() -> None:
    assert "Truncated cases" not in render()
    assert "Truncated cases" not in render(cand=CUT)


def test_html_has_a_not_paired_table() -> None:
    text = render_html(gate_report(**PAIRED), run_of(base_manifest()), run_of(manifest()))
    assert "Not paired (dropped from the comparison)" in text
    assert "answer_relevancy" in text or "Answer relevancy" in text


def test_html_has_no_not_paired_table_without_dropped_cases() -> None:
    text = render_html(gate_report(), run_of(base_manifest()), run_of(manifest()))
    assert "Not paired" not in text


def test_judge_truncated_case_ids_from_a_run() -> None:
    assert judge_truncated_case_ids(run_of(manifest(), truncated=(107, 42))) == [
        "law-0042",
        "law-0107",
    ]
    assert judge_truncated_case_ids(run_of(manifest())) == []


def test_pairing_and_truncation_snapshot(snapshot: SnapshotAssertion) -> None:
    out = render_pr_comment(
        gate_report(**PAIRED),
        base_manifest(),
        CUT,
        report_url="https://example.org/r/1",
        truncated_cases=["law-0042", "law-0107"],
    )
    assert out == snapshot
