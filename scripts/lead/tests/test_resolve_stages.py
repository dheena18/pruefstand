"""Tests of resolve_merge.sh with append-only files left unmerged (real git repos)."""

import contextlib
import subprocess

import pytest
from lead.leadtestenv import Lab, git

BRANCH = "feat/x"
TASKS = "tasks/TASKS.md"


def _resolve(lab: Lab) -> subprocess.CompletedProcess[str]:
    return lab.run("resolve_merge.sh", str(lab.wt), BRANCH)


def _both_append(lab: Lab) -> None:
    lab.write(TASKS, "# Tasks\n\n- t0\n- mine\n")
    lab.commit("mine")
    lab.write(TASKS, "# Tasks\n\n- t0\n- theirs\n", where="other")
    lab.commit("theirs", where="other")
    git(lab.wt, "fetch", "-q", "origin", "main")
    with contextlib.suppress(subprocess.CalledProcessError):
        git(lab.wt, "merge", "--no-commit", "--no-ff", "origin/main")
    assert git(lab.wt, "diff", "--name-only", "--diff-filter=U") == TASKS


def test_taking_one_side_with_checkout_ours_cannot_lose_the_other_sides_rows(lab: Lab) -> None:
    _both_append(lab)
    git(lab.wt, "checkout", "--ours", "--", TASKS)
    res = _resolve(lab)
    assert res.returncode == 1
    assert "a line of theirs is missing: - theirs" in res.stderr
    assert not lab.origin_has(BRANCH)


def test_markers_deleted_by_hand_with_one_side_kept_are_refused(lab: Lab) -> None:
    _both_append(lab)
    lab.write(TASKS, "# Tasks\n\n- t0\n- theirs\n")  # mine is gone
    res = _resolve(lab)
    assert res.returncode == 1
    assert "a line of ours is missing: - mine" in res.stderr
    assert not lab.origin_has(BRANCH)


def test_a_finished_resolution_with_both_sides_is_accepted(lab: Lab) -> None:
    _both_append(lab)
    lab.write(TASKS, "# Tasks\n\n- t0\n- theirs\n- mine\n")  # reordered, nothing lost
    res = _resolve(lab)
    assert res.returncode == 0, res.stderr + res.stdout
    text = git(lab.wt, "show", f"HEAD:{TASKS}")
    assert "- mine" in text
    assert "- theirs" in text


@pytest.mark.parametrize("main_deletes", [True, False])
def test_modify_delete_conflicts_on_an_append_only_file_need_a_human(
    lab: Lab,
    main_deletes: bool,  # noqa: FBT001
) -> None:
    if main_deletes:
        lab.write(TASKS, "# Tasks\n\n- t0\n- mine\n")
        lab.commit("modify")
        (lab.other / TASKS).unlink()
        lab.commit("delete", where="other")
    else:
        (lab.wt / TASKS).unlink()
        lab.commit("delete")
        lab.write(TASKS, "# Tasks\n\n- t0\n- theirs\n", where="other")
        lab.commit("modify", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "no ours/theirs pair" in res.stderr
    assert not lab.origin_has(BRANCH)
    again = _resolve(lab)  # the open merge is still refused, never silently finished
    assert again.returncode == 1
    assert not lab.origin_has(BRANCH)
