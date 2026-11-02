"""Hardening of ``push_dashboard_data``: extras, links, verified bytes, racing pushes (T6.1)."""

from pathlib import Path
from typing import Any

import pytest
from testsupport.dashboard_support import export, push
from testsupport.git_support import bare_repo, commit_count, git, show, tree_names
from testsupport.store_support import run_id, token

from pruefstand.core.errors import StoreError
from pruefstand.store import dashboard_repo

pytestmark = pytest.mark.integration


def test_an_extra_file_with_a_canary_is_refused(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    with pytest.raises(StoreError, match="CANARY-"):
        push(bare, export(tmp_path, 1), extra={"labels.json": token("X").encode()})
    assert git("for-each-ref", git_dir=bare).strip() == ""


def test_a_hard_link_in_the_source_is_refused(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    src = export(tmp_path, 1)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (src / "linked.txt").hardlink_to(outside)
    with pytest.raises(StoreError, match="hard link"):
        push(bare, src)


def test_the_published_bytes_are_the_verified_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = bare_repo(tmp_path)
    src = export(tmp_path, 1)
    real = dashboard_repo._clone_or_init

    def tamper(*args: Any) -> None:
        real(*args)
        (src / "gate.json").write_text(f'{{"status": "{token("LATE")}"}}', encoding="utf-8")

    monkeypatch.setattr(dashboard_repo, "_clone_or_init", tamper)
    push(bare, src)
    assert "CANARY-" not in show(bare, "main", f"runs/{run_id(1)}/gate.json")


def test_a_remote_that_moves_between_clone_and_push_is_retried_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1))
    real = dashboard_repo._clone_or_init
    state = {"moved": False}

    def racing(git_: Any, url: str, branch: str, work: Path) -> None:
        real(git_, url, branch, work)
        if not state["moved"]:
            state["moved"] = True
            push(bare, export(tmp_path, 3, name="racer"))  # someone else pushes meanwhile

    monkeypatch.setattr(dashboard_repo, "_clone_or_init", racing)
    sha = push(bare, export(tmp_path, 2, name="mine"))
    names = tree_names(bare, "main")
    assert f"runs/{run_id(3)}/run.json" in names  # the other push survived
    assert f"runs/{run_id(2)}/run.json" in names
    assert git("rev-parse", "main", git_dir=bare).strip() == sha
    assert commit_count(bare, "main") == 3
