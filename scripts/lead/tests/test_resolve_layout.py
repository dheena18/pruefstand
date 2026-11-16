"""Tests of resolve_merge.sh once main keeps decisions as docs/decisions/D<n>.md (PR #160)."""

import subprocess
from pathlib import Path

from lead.leadtestenv import Lab, git

BRANCH = "feat/x"
FIXTURE = Path(__file__).parent / "fixtures" / "per_file_layout"  # real files of PR #160


def _resolve(lab: Lab) -> subprocess.CompletedProcess[str]:
    return lab.run("resolve_merge.sh", str(lab.wt), BRANCH)


def _row(lab: Lab, row: str) -> None:
    path = lab.wt / "docs" / "decisions.md"
    path.write_text(path.read_text(encoding="utf-8") + row + "\n", encoding="utf-8")
    lab.commit("row")


def _per_file_main(lab: Lab) -> None:
    """Put PR #160's layout (real files) on main: the short page plus docs/decisions/D<n>.md."""
    for src in FIXTURE.rglob("*"):
        if src.is_file():
            lab.write(str(src.relative_to(FIXTURE)), src.read_text(encoding="utf-8"), where="other")
    lab.commit("per-file decisions (#160 layout)", where="other")


def test_a_stale_table_branch_is_stopped_once_main_has_the_per_file_layout(lab: Lab) -> None:
    _row(lab, "| D1230 | mine |")
    _per_file_main(lab)
    res = _resolve(lab)
    assert res.returncode == 1
    assert "build_decisions_index.py --rebase-pending" in res.stderr
    assert (lab.wt / ".git" / "MERGE_HEAD").exists()  # nothing committed, nothing pushed
    assert not lab.origin_has(BRANCH)
    assert "| D1230 | mine |" in (lab.wt / "docs" / "decisions.md").read_text(encoding="utf-8")


def test_rows_added_to_the_page_are_refused_even_when_the_merge_is_clean(lab: Lab) -> None:
    _per_file_main(lab)
    git(lab.wt, "pull", "-q", "origin", "main")  # the branch is current: it has the new layout
    path = lab.wt / "docs" / "decisions.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "| D1230 | sneaked back |\n", encoding="utf-8"
    )
    lab.commit("row on the new page")
    lab.write("later.txt", "x\n", where="other")
    lab.commit("later", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "--rebase-pending" in res.stderr
    assert not lab.origin_has(BRANCH)


def test_tight_and_indented_row_forms_are_detected_too(lab: Lab) -> None:
    _per_file_main(lab)
    git(lab.wt, "pull", "-q", "origin", "main")
    path = lab.wt / "docs" / "decisions.md"
    path.write_text(path.read_text(encoding="utf-8") + "|D1230|x|\n", encoding="utf-8")
    lab.commit("tight row")
    lab.write("later.txt", "x\n", where="other")
    lab.commit("later", where="other")
    res = _resolve(lab)
    assert res.returncode == 1
    assert "--rebase-pending" in res.stderr
