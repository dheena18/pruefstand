"""``--rebase-pending`` / ``--migrate-pending`` on real git repositories: rebase, merge, staging."""

import subprocess
from pathlib import Path

import pytest
from build_decisions_index import check, main
from decisions_files import Decision, parse_file, render_file
from decisions_migrate import find_rows
from decisions_rebase import PrSideError, pr_side, rebase_pending

PAGE_V0 = (
    "# Log\n\n| # | Decision | ADR |\n| --- | --- | --- |\n| D1 | one | - |\n\nPin: a\nOther: x\n"
)
NEW_PAGE = "# Decisions\n\nPin: a\nOther: x\nTail: main\n"


def _git(repo: Path, *args: str, ok: bool = True) -> str:
    env = ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    cmd = ["git", "-C", str(repo), *env, *args]
    done = subprocess.run(  # noqa: S603 - fixed argv
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env={"GIT_EDITOR": "true", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)},
    )
    assert done.returncode == 0 or not ok, done.stderr
    return done.stdout + done.stderr


def _page(repo: Path) -> Path:
    return repo / "docs" / "decisions.md"


def _repo(tmp_path: Path, pr_page: str) -> Path:
    """main = new layout (page + D1.md); branch ``pr`` forked from the old page with ``pr_page``."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _page(repo).write_text(PAGE_V0, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "pr")
    _page(repo).write_text(pr_page, encoding="utf-8")
    _git(repo, "commit", "-qam", "pr")
    _git(repo, "checkout", "-q", "main")
    (repo / "docs" / "decisions").mkdir()
    (repo / "docs" / "decisions" / "D1.md").write_text(
        render_file(Decision("D1", "Log", "one", (("adr", "-"),))), encoding="utf-8"
    )
    _page(repo).write_text(NEW_PAGE, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new layout")
    _git(repo, "checkout", "-q", "pr")
    return repo


PR_PAGE = PAGE_V0.replace("Pin: a", "Pin: b") + "| D1300 | pr decision | - |\n"


def _staged(repo: Path) -> list[str]:
    return _git(repo, "diff", "--cached", "--name-only").split()


def _assert_carried(repo: Path) -> None:
    f = repo / "docs" / "decisions" / "D1300.md"
    assert parse_file(f.read_text(encoding="utf-8")).text == "pr decision"
    assert "docs/decisions/D1300.md" in _staged(repo)
    page = _page(repo).read_text(encoding="utf-8")
    assert "Pin: b" in page
    assert "Other: x" in page
    assert not find_rows(page)
    assert "<<<<" not in page


def test_plain_branch_rows_pin_edit_and_staging(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    res = rebase_pending(repo, "main")
    assert "D1300" in res.written
    assert res.conflicts == 0
    assert "+Pin: b" in res.diff
    assert "-Pin: a" in res.diff
    _assert_carried(repo)


def test_during_git_rebase_head_is_upstream_but_the_pr_side_is_found(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    out = _git(repo, "rebase", "main", ok=False)
    assert "CONFLICT" in out
    assert pr_side(repo) != "HEAD"
    res = rebase_pending(repo, "main")
    assert "D1300" in res.written
    assert res.conflicts == 0
    _assert_carried(repo)
    _git(repo, "rebase", "--continue")
    assert (repo / "docs" / "decisions" / "D1300.md").exists()
    assert "Pin: b" in _page(repo).read_text(encoding="utf-8")
    assert "D1300.md" in _git(repo, "show", "--stat", "--format=", "HEAD")


def test_during_a_conflicted_merge(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    assert "CONFLICT" in _git(repo, "merge", "main", ok=False)
    assert pr_side(repo) == "HEAD"
    res = rebase_pending(repo, "main")
    assert "D1300" in res.written
    _assert_carried(repo)
    _git(repo, "commit", "-q", "--no-edit")
    assert (repo / "docs" / "decisions" / "D1300.md").exists()


def test_unknown_pr_side_during_a_rebase_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    (repo / ".git" / "rebase-merge").mkdir()
    with pytest.raises(PrSideError):
        rebase_pending(repo, "main")
    assert not (repo / "docs" / "decisions" / "D1300.md").exists()


def test_interactive_rebase_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    folder = repo / ".git" / "rebase-merge"
    folder.mkdir()
    (folder / "orig-head").write_text(_git(repo, "rev-parse", "pr").strip(), encoding="utf-8")
    (folder / "interactive").write_text("", encoding="utf-8")
    (folder / "onto").write_text(_git(repo, "rev-parse", "main").strip(), encoding="utf-8")
    (folder / "git-rebase-todo").write_text("# commit dropped by the editor\n", encoding="utf-8")
    with pytest.raises(PrSideError, match="interactive rebase"):
        rebase_pending(repo, "main")
    assert not (repo / "docs" / "decisions" / "D1300.md").exists()


def test_a_real_conflict_of_the_page_is_reported(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    _git(repo, "checkout", "-q", "main")
    _page(repo).write_text(NEW_PAGE.replace("Pin: a", "Pin: c"), encoding="utf-8")
    _git(repo, "commit", "-qam", "main pin")
    _git(repo, "checkout", "-q", "pr")
    res = rebase_pending(repo, "main")
    assert res.conflicts == 1
    assert "<<<<<<<" in _page(repo).read_text(encoding="utf-8")
    assert "docs/decisions/D1300.md" in _staged(repo)


def test_migrate_pending_stages_the_new_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path, PR_PAGE)
    _git(repo, "merge", "-q", "main", ok=False)
    _git(repo, "checkout", "-q", "--theirs", "docs/decisions.md")
    _page(repo).write_text(NEW_PAGE + "| D1301 | late row | - |\n", encoding="utf-8")
    base = ["--dir", str(repo / "docs" / "decisions"), "--decisions-md", str(_page(repo))]
    assert main([*base, "--migrate-pending"]) == 0
    assert "docs/decisions/D1301.md" in _staged(repo)


@pytest.mark.parametrize(
    "line",
    [
        "|D1301|x|-|",
        " | D1301 | indented row | - |",
        "### D1301 new decision",
        "D1301 is decided: x",
        "- **D1301** x",
        "**D1301** x",
        "1. D1301 x",
        "+ D1301 x",
        "> | D1301 | quoted | - |",
        "| x | D1301 | y |",
    ],
)
def test_guard_bypass_forms_are_caught(tmp_path: Path, line: str) -> None:
    md = tmp_path / "decisions.md"
    md.write_text(NEW_PAGE + line + "\n", encoding="utf-8")
    out = tmp_path / "decisions"
    out.mkdir()
    (out / "D1.md").write_text(render_file(Decision("D1", "", "x")), encoding="utf-8")
    assert check(out, md), line


def test_a_tight_or_indented_row_is_migratable(tmp_path: Path) -> None:
    md = tmp_path / "decisions.md"
    md.write_text("|D1301|tight|-|\n | D1302 | indented | - |\n", encoding="utf-8")
    assert [
        (r.decision.id, r.decision.text) for r in find_rows(md.read_text(encoding="utf-8"))
    ] == [
        ("D1301", "tight"),
        ("D1302", "indented"),
    ]
