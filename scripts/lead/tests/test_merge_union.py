"""Tests of the union-merge helper (pure functions and the CLI)."""

import subprocess
import sys
from pathlib import Path

import pytest
from lead.leadtestenv import LEAD, git
from lead.merge_union import decision_counts, excess_duplicates, is_append_only, resolve_text


def test_resolve_keeps_both_sides_dedups_across_sides_and_orders_rows() -> None:
    src = (
        "h\n<<<<<<< HEAD\n| D3 | c |\n| D2 | b |\n=======\n| D2 | b |\n| D1 | a |\n"
        ">>>>>>> origin/main\nt\n"
    )
    new, blocks = resolve_text(src, rows=True)
    assert blocks == 1
    assert new == "h\n| D1 | a |\n| D2 | b |\n| D3 | c |\nt\n"


def test_repeated_lines_within_one_side_are_kept_so_code_fences_survive() -> None:
    src = "<<<<<<< a\n```\ncode\n```\n```\nmore\n```\n=======\nother\n>>>>>>> b\n"
    new, _ = resolve_text(src, rows=False)
    assert new == "```\ncode\n```\n```\nmore\n```\nother\n"


def test_non_row_lines_stay_in_place_when_rows_are_sorted() -> None:
    src = "<<<<<<< a\n| D5 | e |\nnote\n| D3 | c |\n=======\n| D4 | d |\n>>>>>>> b\n"
    new, _ = resolve_text(src, rows=True)
    assert new == "| D3 | c |\nnote\n| D4 | d |\n| D5 | e |\n"


def test_resolve_plain_lines_and_diff3_base_dropped() -> None:
    src = "<<<<<<< a\nx\n||||||| base\nold\n=======\ny\n>>>>>>> b\n"
    assert resolve_text(src, rows=False) == ("x\ny\n", 1)


def test_unterminated_block_is_an_error() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        resolve_text("<<<<<<< a\nx\n=======\n", rows=False)


def test_duplicates_are_counted_against_the_reference() -> None:
    assert decision_counts("| D1 | a |\n| D1 | b |\n")[1] == 2
    assert excess_duplicates("| D1 | a |\n| D1 | b |\n", "| D1 | a |\n| D1 | b |\n") == []
    assert excess_duplicates("| D1 | a |\n| D1 | b |\n", "") == [1]
    assert excess_duplicates("| D1 | a |\n| D2 | b |\n", "") == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/decisions.md", True),
        ("docs/decisions/D1200.md", False),
        ("docs/decisions/anything.md", False),
        ("tasks/TASKS.md", True),
        ("src/a.py", False),
    ],
)
def test_allow_list(path: str, expected: bool) -> None:  # noqa: FBT001
    assert is_append_only(path) is expected


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv
        [sys.executable, "-I", str(LEAD / "merge_union.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_cli_dupes_resolve_and_atomic_write(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "docs").mkdir()
    (repo / "docs" / "decisions.md").write_text("| D1 | a |\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    (repo / "docs" / "decisions.md").write_text("| D1 | a |\n| D1 | b |\n", encoding="utf-8")
    run = _run(repo, "dupes", "HEAD", "docs/decisions.md")
    assert run.returncode == 1
    assert "DUPLICATE D-number D1" in run.stderr
    other = _run(repo, "resolve", "src/a.py")
    assert other.returncode == 1
    assert "NEEDS MANUAL" in other.stderr
    conflict = "a\n<<<<<<< x\n| D2 | b |\n=======\n| D1 | c |\n>>>>>>> y\n"
    (repo / "docs" / "decisions.md").write_text(conflict, encoding="utf-8")
    (repo / "docs" / "decisions.md").chmod(0o640)
    assert _run(repo, "resolve", "docs/decisions.md").returncode == 0
    assert (repo / "docs" / "decisions.md").read_text(
        encoding="utf-8"
    ) == "a\n| D1 | c |\n| D2 | b |\n"
    assert (repo / "docs" / "decisions.md").stat().st_mode & 0o777 == 0o640
    assert not list((repo / "docs").glob("*.lead-tmp"))
    assert _run(repo, "resolve", "docs/decisions.md").returncode == 1  # no markers any more
    assert _run(repo, "docs").returncode == 2
