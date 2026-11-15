"""Tests of resolve_merge.sh (real git repos, fake uv)."""

import subprocess

from lead.leadtestenv import Lab, git

BRANCH = "feat/x"


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


def test_decisions_conflict_keeps_both_sides_in_order(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1220 | theirs |", where="other", msg="theirs")
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    text = (lab.wt / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert text.index("| D1220 | theirs |") < text.index("| D1230 | mine |")
    assert "<<<<<<<" not in text


def test_docs_decisions_directory_is_append_only_too(lab: Lab) -> None:
    lab.write("docs/decisions/d12.md", "| D1200 | a |\n", where="other")
    lab.commit("base dir", where="other")
    git(lab.wt, "pull", "-q", "origin", "main")
    lab.write("docs/decisions/d12.md", "| D1200 | a |\n| D1210 | mine |\n")
    lab.commit("mine")
    lab.write("docs/decisions/d12.md", "| D1200 | a |\n| D1211 | theirs |\n", where="other")
    lab.commit("theirs", where="other")
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    text = (lab.wt / "docs/decisions/d12.md").read_text(encoding="utf-8")
    assert "D1210" in text
    assert "D1211" in text


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
    again = _resolve(lab)
    assert again.returncode == 0, again.stderr + again.stdout
    assert "previous run did not finish" in again.stdout
    assert lab.origin_has(BRANCH)
    assert "D1231" in git(lab.wt, "show", "HEAD:docs/decisions.md")


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


def test_dry_run_reports_and_changes_nothing(lab: Lab) -> None:
    _decisions(lab, "| D1230 | mine |", where="wt", msg="mine")
    _decisions(lab, "| D1220 | theirs |", where="other", msg="theirs")
    head = git(lab.wt, "rev-parse", "HEAD")
    res = _resolve(lab, dry=True)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "DRY-RUN: conflicts in: docs/decisions.md" in res.stdout
    assert "both sides would be kept" in res.stdout
    assert git(lab.wt, "rev-parse", "HEAD") == head
    assert not (lab.wt / ".git" / "MERGE_HEAD").exists()
    assert not (lab.wt / ".git" / "lead-resolve-merge.state").exists()
    lab.write("mine.txt", "m\n")
    lab.commit("m2")
    lab.write("other.txt", "theirs\n", where="other")
    lab.commit("t2", where="other")
    lab.write("other.txt", "mine\n")
    lab.commit("m3")
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
    state = (lab.wt / ".git" / "lead-resolve-merge.state").read_text(encoding="utf-8")
    assert "phase=test" in state
