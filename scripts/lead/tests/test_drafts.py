"""Tests of draft_push.sh, draft_update.sh and install_wrappers.sh (real git, fake gh and uv)."""

from pathlib import Path

import pytest
from lead.leadtestenv import LEAD, Lab, git

BRANCH = "feat/x"


def _push(
    lab: Lab, msg: Path, body: Path, *extra: str, cwd: Path | None = None
) -> tuple[int, str, str]:
    res = lab.run(
        "draft_push.sh", *extra, str(lab.wt), BRANCH, "the title", str(msg), str(body), cwd=cwd
    )
    return res.returncode, res.stdout, res.stderr


def test_draft_push_commits_pushes_and_opens_a_draft_pr_against_main(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    msg, body = lab.msg("m.txt", "feat: add new\n"), lab.msg("b.md", "body\n")
    rc, out, err = _push(lab, msg, body)
    assert rc == 0, out + err
    assert "pull/1" in out
    assert git(lab.wt, "log", "-1", "--format=%s") == "feat: add new"
    assert lab.origin_has(BRANCH)
    expected = (
        "pr create --draft --repo dheena18/pruefstand --base main --head feat/x --title the title"
    )
    assert expected in lab.gh_log()
    assert "--body-file" in lab.gh_log()


@pytest.mark.parametrize(
    "bad",
    [
        "feat: x\n\nClaude-Session: https://claude.ai/code/session_1\n",
        "x\n\n🤖 Generated with [Claude Code](https://claude.com)\n",
        "generated with claude code\n",
    ],
)
@pytest.mark.parametrize("which", ["msg", "body"])
def test_footer_in_message_or_body_is_refused(lab: Lab, bad: str, which: str) -> None:
    lab.write("new.py", "Y = 2\n")
    msg = lab.msg("m.txt", bad if which == "msg" else "feat: ok\n")
    body = lab.msg("b.md", bad if which == "body" else "fine\n")
    rc, _, err = _push(lab, msg, body)
    assert rc == 2
    assert "owner rule" in err
    assert not lab.origin_has(BRANCH)
    assert lab.gh_log() == ""
    assert git(lab.wt, "log", "-1", "--format=%s") == "seed"


def test_update_refuses_a_footer_too(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    msg = lab.msg("m.txt", "fix: x\n\nClaude-Session: abc\n")
    assert lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg)).returncode == 2
    assert not lab.origin_has(BRANCH)


def test_ruff_failures_stop_before_commit(lab: Lab) -> None:
    msg, body = lab.msg("m.txt", "feat: x\n"), lab.msg("b.md", "b\n")
    lab.write("bad.py", "import os\n")
    rc, out, _ = _push(lab, msg, body)
    assert (rc, "RUFF_FAIL" in out) == (1, True)
    lab.write("bad.py", "x   =   1\n")
    rc, out, _ = _push(lab, msg, body)
    assert (rc, "FORMAT_FAIL" in out) == (1, True)
    assert git(lab.wt, "log", "-1", "--format=%s") == "seed"
    assert not lab.origin_has(BRANCH)


def test_wrong_or_main_branch_is_refused(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    msg, body = lab.msg("m.txt", "feat: x\n"), lab.msg("b.md", "b\n")
    res = lab.run("draft_push.sh", str(lab.wt), "feat/other", "t", str(msg), str(body))
    assert res.returncode == 2
    git(lab.wt, "checkout", "-q", "main")
    res = lab.run("draft_push.sh", str(lab.wt), "main", "t", str(msg), str(body))
    assert res.returncode == 2
    assert "refusing" in res.stderr


def test_works_from_any_cwd_with_relative_message_paths(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    lab.msg("m.txt", "feat: rel\n")
    lab.msg("b.md", "b\n")
    res = lab.run("draft_push.sh", str(lab.wt), BRANCH, "t", "m.txt", "b.md", cwd=lab.root)
    assert res.returncode == 0, res.stderr
    assert git(lab.wt, "log", "-1", "--format=%s") == "feat: rel"


def test_dry_run_changes_nothing(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    msg, body = lab.msg("m.txt", "feat: x\n"), lab.msg("b.md", "b\n")
    rc, out, err = _push(lab, msg, body, "--dry-run")
    assert rc == 0, out + err
    assert "DRY-RUN" in out
    assert git(lab.wt, "log", "-1", "--format=%s") == "seed"
    assert not lab.origin_has(BRANCH)
    assert lab.gh_log() == ""


def test_update_commits_and_pushes_plain(lab: Lab) -> None:
    lab.write("new.py", "Y = 2\n")
    msg = lab.msg("m.txt", "fix: more\n")
    res = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))
    assert res.returncode == 0, res.stderr
    assert lab.origin_has(BRANCH)
    again = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))  # nothing staged: still fine
    assert again.returncode == 0
    assert "nothing staged" in again.stdout


def test_scripts_never_force_push() -> None:
    for name in ("lib.sh", "draft_push.sh", "draft_update.sh", "resolve_merge.sh"):
        text = (LEAD / name).read_text(encoding="utf-8")
        assert "--force" not in text
        assert "push -f" not in text
        assert "--admin" not in text


def test_usage_errors(lab: Lab) -> None:
    assert lab.run("draft_push.sh").returncode == 2
    assert lab.run("draft_update.sh", "only-one").returncode == 2
    assert lab.run("resolve_merge.sh", "one").returncode == 2


def test_wrappers_exec_the_main_checkouts_scripts_after_a_fetch(lab: Lab) -> None:
    bin_dir = lab.root / "wrappers"
    res = lab.run("install_wrappers.sh", "--dir", str(bin_dir), "--main", str(lab.other))
    assert res.returncode == 0, res.stderr
    for name in ("lead-draft-push", "lead-draft-update", "lead-resolve-merge"):
        assert (bin_dir / name).stat().st_mode & 0o111
    author = lab.root / "author"
    git(lab.root, "clone", "-q", str(lab.origin), str(author))
    (author / "later.txt").write_text("x\n", encoding="utf-8")  # main moves on
    git(author, "add", "-A")
    git(author, "commit", "-q", "-m", "later")
    git(author, "push", "-q", "origin", "main")
    res = lab.run(
        str(bin_dir / "lead-draft-push"), cwd=lab.wt
    )  # called from a worktree, wrapper outside
    assert res.returncode == 2
    assert "usage: draft_push.sh" in res.stderr
    assert (lab.other / "later.txt").exists()


def test_wrapper_dry_run_writes_nothing(lab: Lab) -> None:
    bin_dir = lab.root / "wrappers"
    res = lab.run(
        "install_wrappers.sh", "--dry-run", "--dir", str(bin_dir), "--main", str(lab.other)
    )
    assert res.returncode == 0
    assert "DRY-RUN" in res.stdout
    assert not bin_dir.exists()
    assert lab.run("install_wrappers.sh", "--bogus").returncode == 2
