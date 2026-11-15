"""D1082: the PR comment shows timeouts next to error_rate (no gate change)."""

from testsupport.report_builders import base_manifest, gate_report, manifest

from pruefstand.report.markdown import render_pr_comment


def _comment(counts: dict[str, int]) -> str:
    return render_pr_comment(
        gate_report(), base_manifest(), manifest(counts=counts), report_url=None
    )


def test_timeouts_get_their_own_line() -> None:
    out = _comment({"ok": 18, "error": 2, "timeout": 2})
    assert "Timeouts: 2 cases timed out (scored as candidate errors in error_rate)." in out


def test_one_timeout_is_singular() -> None:
    assert "Timeouts: 1 case timed out" in _comment({"ok": 19, "error": 1, "timeout": 1})


def test_no_timeout_line_without_timeouts() -> None:
    assert "Timeouts:" not in _comment({"ok": 20})


def test_cases_not_run_after_timeouts_are_shown_next_to_timeouts() -> None:
    out = _comment({"ok": 2, "error": 18, "timeout": 3, "aborted_after_timeouts": 15})
    assert "Timeouts: 3 cases timed out (scored as candidate errors in error_rate)." in out
    assert (
        "Not run: 15 cases after consecutive timeouts (runner.max_consecutive_timeouts; "
        "recorded as candidate errors)." in out
    )


def test_no_not_run_line_without_an_abort() -> None:
    assert "Not run:" not in _comment({"ok": 19, "error": 1, "timeout": 1})
