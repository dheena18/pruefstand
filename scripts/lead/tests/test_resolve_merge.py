"""Tests of resolve_merge.sh (real git repos, fake uv and git)."""

import contextlib
import subprocess

from lead.leadtestenv import Lab, git

BRANCH = "feat/x"
FRONT_MATTER = "---\nid: D1200\nstatus: accepted\n---\n\n"


def _resolve(
    lab: Lab, *args: str, extra_env: dict[str, str] | None = None, dry: bool = False
) -> subprocess.CompletedProcess[str]:
    flags = ["--dry-run"] if dry else []
    return lab.run("resolve_merge.sh", *flags, str(lab.wt), BRANCH, *args, extra_env=extra_env)


def _decisions(lab: Lab, row: str, *, where: str, msg: str) -> None:
    base = lab.wt if where == "wt" else lab.other
    path = base / "docs" / "decisions.md"
    path.write_text(path.read_text(encoding="utf-8") + row + "\n", encoding="utf-8")
    lab.commit(msg, where=where)


def test_clean_merge_commits_and_pushes(lab: Lab) -> None:
    lab.write("mine.txt", "m\n")
    lab.commit("mine")
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    assert git(lab.wt, "log", "-1", "--format=%s") == f"merge main into {BRANCH}"
    assert (lab.wt / "theirs.txt").exists()
    assert git(lab.origin, "rev-parse", f"refs/heads/{BRANCH}") == git(lab.wt, "rev-parse", "HEAD")
    pushes = [ln for ln in lab.git_log().splitlines() if ln.startswith("push")]
    assert pushes == [f"push -q origin refs/heads/{BRANCH}:refs/heads/{BRANCH}"]


def test_decisions_conflict_keeps_both_sides_in_order(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1220 | theirs |", where="other", msg="theirs")
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    text = (lab.wt / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert text.index("| D1220 | theirs |") < text.index("| D1230 | mine |")
    assert "<<<<<<<" not in text


def test_per_decision_files_with_different_names_merge_cleanly(lab: Lab) -> None:
    lab.write("docs/decisions/D1201.md", FRONT_MATTER.replace("D1200", "D1201") + "mine\n")
    lab.commit("mine")
    lab.write(
        "docs/decisions/D1202.md",
        FRONT_MATTER.replace("D1200", "D1202") + "theirs\n",
        where="other",
    )
    lab.commit("theirs", where="other")
    assert _resolve(lab).returncode == 0
    assert (lab.wt / "docs/decisions/D1202.md").exists()


def test_same_decision_file_added_on_both_sides_needs_a_human(lab: Lab) -> None:
    lab.write("docs/decisions/D1200.md", FRONT_MATTER + "Our reasoning.\n")
    lab.commit("mine")
    lab.write(
        "docs/decisions/D1200.md",
        FRONT_MATTER + "Their reasoning, a different decision.\n",
        where="other",
    )
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "NEEDS MANUAL: docs/decisions/D1200.md" in res.stderr
    assert (lab.wt / ".git" / "MERGE_HEAD").exists()
    assert not lab.origin_has(BRANCH)
    dry = _resolve(
        lab, dry=True
    )  # a content conflict anywhere under docs/decisions/ is never auto-resolved
    assert dry.returncode == 1


def test_a_merge_of_something_else_in_progress_is_not_resumed_or_pushed(lab: Lab) -> None:
    git(lab.wt, "checkout", "-q", "-b", "side")
    lab.write("other.txt", "side\n")
    lab.commit("side")
    git(lab.wt, "checkout", "-q", BRANCH)
    lab.write("other.txt", "mine\n")
    lab.commit("mine")
    with contextlib.suppress(subprocess.CalledProcessError):
        git(lab.wt, "merge", "--no-commit", "side")
    merge_head = git(lab.wt, "rev-parse", "MERGE_HEAD")
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "merge of something else is in progress" in res.stderr
    assert git(lab.wt, "rev-parse", "MERGE_HEAD") == merge_head
    assert not lab.origin_has(BRANCH)


def test_duplicate_d_number_stops_before_commit_and_a_rerun_resumes(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1230 | theirs |", where="other", msg="theirs")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "DUPLICATE D-number D1230" in res.stderr
    assert "STOPPED in phase 'verify'" in res.stderr
    assert (lab.wt / ".git" / "MERGE_HEAD").exists()  # half merge, not committed
    assert not lab.origin_has(BRANCH)
    path = lab.wt / "docs" / "decisions.md"  # the owner renumbers by hand
    path.write_text(
        path.read_text(encoding="utf-8").replace("| D1230 | mine |", "| D1231 | mine |"),
        encoding="utf-8",
    )
    unstaged = _resolve(lab)  # the commit would not contain the edit: refused until it is staged
    assert unstaged.returncode == 1
    assert "unstaged edits to files of this merge" in unstaged.stderr
    assert "docs/decisions.md" in unstaged.stderr
    git(lab.wt, "add", "docs/decisions.md")
    again = _resolve(lab)
    assert again.returncode == 0, again.stderr + again.stdout
    assert "previous run did not finish" in again.stdout
    assert lab.origin_has(BRANCH)
    assert "D1231" in git(lab.wt, "show", "HEAD:docs/decisions.md")


def test_a_run_killed_after_writing_the_resolution_but_before_git_add_finishes_on_rerun(
    lab: Lab,
) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1220 | theirs |", where="other", msg="theirs")
    git(lab.wt, "fetch", "-q", "origin", "main")
    with contextlib.suppress(subprocess.CalledProcessError):
        git(lab.wt, "merge", "--no-commit", "--no-ff", "origin/main")
    path = lab.wt / "docs" / "decisions.md"  # what the helper's atomic write leaves behind
    path.write_text(
        "# Decisions\n\n| D1 | one |\n| D2 | two |\n| D1220 | theirs |\n| D1230 | mine |\n",
        encoding="utf-8",
    )
    assert (
        git(lab.wt, "diff", "--name-only", "--diff-filter=U") == "docs/decisions.md"
    )  # still unmerged
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    text = git(lab.wt, "show", "HEAD:docs/decisions.md")
    assert "D1220" in text
    assert "D1230" in text


def test_a_marker_free_unmerged_file_that_is_not_append_only_needs_a_human(lab: Lab) -> None:
    lab.write("other.txt", "mine\n")
    lab.commit("mine")
    lab.write("other.txt", "theirs\n", where="other")
    lab.commit("theirs", where="other")
    git(lab.wt, "fetch", "-q", "origin", "main")
    with contextlib.suppress(subprocess.CalledProcessError):
        git(lab.wt, "merge", "--no-commit", "--no-ff", "origin/main")
    lab.write("other.txt", "edited without git add\n")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "unmerged without conflict markers" in res.stderr
    assert not lab.origin_has(BRANCH)


def test_a_resumed_merge_does_not_sweep_unrelated_edits_into_the_merge_commit(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1230 | theirs |", where="other", msg="theirs")
    assert _resolve(lab).returncode == 1  # duplicate D-number, merge left open
    (lab.wt / "a.py").write_text("X = 99\n", encoding="utf-8")  # an unrelated edit made meanwhile
    path = lab.wt / "docs" / "decisions.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("| D1230 | mine |", "| D1231 | mine |"),
        encoding="utf-8",
    )
    git(lab.wt, "add", "docs/decisions.md")
    assert _resolve(lab).returncode == 0
    assert "a.py" not in git(lab.wt, "show", "--name-only", "--format=", "HEAD")
    assert (lab.wt / "a.py").read_text(encoding="utf-8") == "X = 99\n"  # still a local edit


def test_other_conflicts_need_a_human_and_a_rerun_after_resolving_completes(lab: Lab) -> None:
    lab.write("other.txt", "mine\n")
    lab.commit("mine")
    lab.write("other.txt", "theirs\n", where="other")
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "NEEDS MANUAL: other.txt" in res.stderr
    assert not lab.origin_has(BRANCH)
    lab.write("other.txt", "both\n")
    git(lab.wt, "add", "other.txt")
    again = _resolve(lab)
    assert again.returncode == 0, again.stderr
    assert git(lab.wt, "show", "HEAD:other.txt") == "both"


def test_conflict_markers_are_never_committed(lab: Lab) -> None:
    lab.write("mine.txt", "m\n")
    lab.commit("mine")
    lab.write("notes.txt", "<<<<<<< oops\nx\n>>>>>>> oops\n", where="other")
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "MARKERS_LEFT" in res.stdout
    assert (lab.wt / ".git" / "MERGE_HEAD").exists()
    assert not lab.origin_has(BRANCH)


def test_already_merged_is_idempotent(lab: Lab) -> None:
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    assert _resolve(lab).returncode == 0
    tip = git(lab.wt, "rev-parse", "HEAD")
    again = _resolve(lab)
    assert again.returncode == 0
    assert "already merged" in again.stdout
    assert git(lab.wt, "rev-parse", "HEAD") == tip


def test_dirty_worktree_is_refused(lab: Lab) -> None:
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    (lab.wt / "a.py").write_text("X = 99\n", encoding="utf-8")
    res = _resolve(lab)
    assert res.returncode == 2
    assert "uncommitted" in res.stderr


def test_dry_run_reports_without_fetching_or_changing_anything(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1220 | theirs |", where="other", msg="theirs")
    git(lab.wt, "fetch", "-q", "origin", "main")  # dry-run uses the local origin/main
    head = git(lab.wt, "rev-parse", "HEAD")
    before = lab.git_log().count("fetch")
    res = _resolve(lab, dry=True)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "no fetch" in res.stdout
    assert "DRY-RUN: conflicts in: docs/decisions.md" in res.stdout
    assert "both sides would be kept" in res.stdout
    assert lab.git_log().count("fetch") == before
    assert git(lab.wt, "rev-parse", "HEAD") == head
    assert not (lab.wt / ".git" / "MERGE_HEAD").exists()
    assert not (lab.wt / ".git" / "lead-resolve-merge.state").exists()
    lab.write("other.txt", "theirs\n", where="other")
    lab.commit("t2", where="other")
    lab.write("other.txt", "mine\n")
    lab.commit("m3")
    git(lab.wt, "fetch", "-q", "origin", "main")
    manual = _resolve(lab, dry=True)
    assert manual.returncode == 1
    assert "NEEDS MANUAL: other.txt" in manual.stderr


def test_pytest_args_run_and_a_timeout_is_reported_not_silent(lab: Lab) -> None:
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    lab.write("test_ok.py", "def test_ok() -> None:\n    assert True\n")
    lab.commit("tests")
    ok = _resolve(lab, "test_ok.py")
    assert ok.returncode == 0, ok.stderr + ok.stdout
    assert "1 passed" in ok.stdout
    lab.write("test_slow.py", "import time\n\n\ndef test_slow() -> None:\n    time.sleep(30)\n")
    lab.commit("slow")
    lab.write("more.txt", "m\n", where="other")
    lab.commit("more", where="other")
    slow = _resolve(lab, "test_slow.py", extra_env={"LEAD_TEST_TIMEOUT": "2"})
    assert slow.returncode == 1
    assert "TEST_TIMEOUT" in slow.stdout
    assert "STOPPED in phase 'test'" in slow.stderr
    assert "phase=test" in (lab.wt / ".git" / "lead-resolve-merge.state").read_text(
        encoding="utf-8"
    )


def test_unstaged_edit_is_found_under_a_collating_locale(lab: Lab) -> None:
    """comm under en_US.UTF-8 disagrees with sort on punctuated names and missed the overlap."""
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    for name in ("a-c.txt", "ab.txt", "a_b.txt", "a.txt"):
        lab.write(name, "t\n", where="other")
    lab.commit("theirs files", where="other")
    _decisions(lab, "| D1230 | theirs |", where="other", msg="theirs")
    env = {"LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
    stopped = _resolve(lab, extra_env=env)
    assert "DUPLICATE D-number D1230" in stopped.stderr
    (lab.wt / "a-c.txt").write_text("edited after the merge\n", encoding="utf-8")
    refused = _resolve(lab, extra_env=env)
    assert refused.returncode == 1
    assert "unstaged edits to files of this merge" in refused.stderr
    assert "a-c.txt" in refused.stderr
