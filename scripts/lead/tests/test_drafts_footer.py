"""Tests of the footer rules of draft_push.sh and draft_update.sh (real git, fake gh/git/uv)."""

from pathlib import Path

from lead.leadtestenv import Lab, git

BRANCH = "feat/x"


def _push(lab: Lab, msg: Path, body: Path, *extra: str) -> tuple[int, str, str]:
    res = lab.run("draft_push.sh", *extra, str(lab.wt), BRANCH, "the title", str(msg), str(body))
    return res.returncode, res.stdout, res.stderr


def _ready(lab: Lab, name: str = "new.py") -> tuple[Path, Path]:
    lab.write(name, "Y = 2\n")
    return lab.msg("m.txt", "feat: add new\n"), lab.msg("b.md", "body\n")


def test_update_refuses_a_footer_too(lab: Lab) -> None:
    lab.write("a.py", "X = 2\n")
    msg = lab.msg("m.txt", "fix: x\n\nClaude-Session: abc\n")
    assert lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg)).returncode == 2
    assert not lab.origin_has(BRANCH)


def test_a_footer_added_by_a_commit_hook_is_caught_before_the_push(lab: Lab) -> None:
    hook = lab.wt / ".git" / "hooks" / "commit-msg"
    hook.write_text(
        '#!/bin/sh\nprintf "\\nClaude-Session: injected\\n" >> "$1"\n', encoding="utf-8"
    )
    hook.chmod(0o755)
    msg, body = _ready(lab)
    rc, _, err = _push(lab, msg, body, "--add", "new.py")
    assert rc == 2
    assert "commit message" in err
    assert not lab.origin_has(BRANCH)
    assert lab.gh_log() == ""


def test_a_second_run_after_a_footer_refusal_never_pushes_the_commit(lab: Lab) -> None:
    hook = lab.wt / ".git" / "hooks" / "commit-msg"
    hook.write_text(
        '#!/bin/sh\nprintf "\\nClaude-Session: injected\\n" >> "$1"\n', encoding="utf-8"
    )
    hook.chmod(0o755)
    msg, body = _ready(lab)
    assert _push(lab, msg, body, "--add", "new.py")[0] == 2
    assert (
        git(lab.wt, "log", "-1", "--format=%B").count("Claude-Session") == 1
    )  # the commit exists locally
    again = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))  # nothing is staged any more
    assert again.returncode == 2
    assert "commit message" in again.stderr
    assert not lab.origin_has(BRANCH)
    assert not any(ln.startswith("push") for ln in lab.git_log().splitlines())


def test_a_footer_commit_on_a_side_branch_merged_with_no_ff_is_caught(lab: Lab) -> None:
    git(lab.wt, "checkout", "-q", "-b", "side")
    lab.write("side.txt", "s\n")
    lab.commit("side work\n\nClaude-Session: https://claude.ai/code/session_x")
    git(lab.wt, "checkout", "-q", BRANCH)
    git(lab.wt, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    msg = lab.msg("m.txt", "fix: nothing to add\n")
    res = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))
    assert res.returncode == 2
    assert "not on origin yet" in res.stderr
    assert not lab.origin_has(BRANCH)


def test_footers_in_history_that_origin_already_has_do_not_block(lab: Lab) -> None:
    lab.write("old.txt", "o\n", where="other")
    lab.commit("old work\n\nClaude-Session: https://claude.ai/code/session_old", where="other")
    git(lab.wt, "pull", "-q", "origin", "main")  # the footer commit arrives through main
    lab.write("a.py", "X = 8\n")
    msg = lab.msg("m.txt", "fix: fine\n")
    res = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))
    assert res.returncode == 0, res.stderr
    git(
        lab.wt, "update-ref", "-d", "refs/remotes/origin/main"
    )  # even a missing origin/main must not block
    lab.write("a.py", "X = 9\n")
    again = lab.run("draft_update.sh", str(lab.wt), BRANCH, str(msg))
    assert again.returncode == 0, again.stderr
