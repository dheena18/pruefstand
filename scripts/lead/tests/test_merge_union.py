"""Tests of the union-merge helper (pure functions and the CLI)."""

import subprocess
import sys
from pathlib import Path

import pytest
from lead.leadtestenv import LEAD, git
from lead.merge_union import decision_counts, excess_duplicates, is_append_only, resolve_text


def test_resolve_keeps_both_sides_dedups_and_orders_rows() -> None:
    src = (
        "h\n<<<<<<< HEAD\n| D3 | c |\n| D2 | b |\n=======\n| D2 | b |\n| D1 | a |\n"
        ">>>>>>> origin/main\nt\n"
    )
    new, blocks = resolve_text(src, rows=True)
    assert blocks == 1
    assert new == "h\n| D1 | a |\n| D2 | b |\n| D3 | c |\nt\n"


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
        ("docs/decisions/x.md", True),
        ("tasks/TASKS.md", True),
        ("src/a.py", False),
    ],
)
def test_allow_list(path: str, expected: bool) -> None:  # noqa: FBT001
    assert is_append_only(path) is expected


def test_cli_resolve_and_dupes(tmp_path: Path) -> None:
    helper = str(LEAD / "merge_union.py")
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "docs").mkdir()
    (repo / "docs" / "decisions.md").write_text("| D1 | a |\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    (repo / "docs" / "decisions.md").write_text("| D1 | a |\n| D1 | b |\n", encoding="utf-8")
    run = subprocess.run(  # noqa: S603  # fixed argv
        [sys.executable, "-I", helper, "dupes", "HEAD", "docs/decisions.md"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert run.returncode == 1
    assert "DUPLICATE D-number D1" in run.stderr
    other = subprocess.run(  # noqa: S603  # fixed argv
        [sys.executable, "-I", helper, "resolve", "src/a.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert other.returncode == 1
    assert "NEEDS MANUAL" in other.stderr
    assert subprocess.run([sys.executable, "-I", helper], check=False, timeout=60).returncode == 2  # noqa: S603
