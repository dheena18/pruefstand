"""``action/check_comment.py``: the comment gate in front of the upsert step (T1.12 S5)."""

from pathlib import Path

import pytest
from check_comment import MARKER, MAX_CHARS, check_comment, main

BODY = f"{MARKER}\n## Prüfstand: ✅ PASS\n\nAlles in Ordnung.\n"


def test_a_valid_comment_has_no_findings() -> None:
    assert check_comment(BODY) == []


def test_a_missing_marker_is_an_error() -> None:
    (finding,) = check_comment("## Prüfstand: ✅ PASS\n")
    assert "marker" in finding


def test_the_marker_must_be_the_first_line() -> None:
    assert check_comment(f"intro\n{BODY}") != []


def test_an_empty_comment_is_an_error() -> None:
    assert check_comment("") != []


def test_the_length_limit_is_inclusive() -> None:
    at_limit = BODY + "x" * (MAX_CHARS - len(BODY))
    assert len(at_limit) == MAX_CHARS
    assert check_comment(at_limit) == []
    (finding,) = check_comment(at_limit + "x")
    assert "60000" in finding.replace(" ", "")


def test_a_secrets_expression_is_just_text() -> None:
    assert check_comment(BODY + "${{ secrets.X }} and <script>alert(1)</script>\n") == []


def test_main_reads_the_file_and_sets_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "good.md"
    good.write_text(BODY, encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("no marker\n", encoding="utf-8")
    assert main([str(good)]) == 0
    assert main([str(bad)]) == 1
    assert "marker" in capsys.readouterr().err
    assert main([str(tmp_path / "missing.md")]) == 2
    assert main([]) == 2
