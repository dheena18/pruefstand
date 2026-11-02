"""``GitBranchBaselineStore`` against a local bare repository (T6.1 S4, X2.7, R9-17)."""

import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from testsupport.git_support import bare_repo, commit_count, git, reject_pushes, show, tree_names
from testsupport.run_builders import unhashed
from testsupport.store_support import FP, run_id, run_of

from pruefstand.core.errors import StoreError, StoreIntegrityError

pytestmark = pytest.mark.integration

START = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def clock() -> Callable[[], datetime]:
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return START + timedelta(seconds=state["n"])

    return tick


class Setup:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.bare = bare_repo(tmp_path)
        self.data_root = tmp_path / "data" / "baselines"
        self.data_root.mkdir(parents=True)

    def store(self, **kwargs: Any) -> GitBranchBaselineStore:
        return GitBranchBaselineStore(
            "owner/private",
            self.data_root,
            remote=str(self.bare),
            clock=kwargs.pop("clock", clock()),
            **kwargs,
        )


@pytest.fixture
def env(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_put_writes_the_files_under_the_data_root_and_only_the_index_into_git(env: Setup) -> None:
    run = run_of(env.tmp, 1)
    env.store().put(run, "main")
    base = env.data_root / FP
    assert (base / "main" / "run.json").is_file()
    assert (base / "main" / "responses.jsonl.zst").is_file()
    assert (base / "history" / run_id(1) / "run.json").is_file()
    assert not (base / "history" / run_id(1) / "responses.jsonl.zst").exists()
    assert tree_names(env.bare, "baselines") == ["baselines/index.json"]


def test_the_index_pins_the_manifest_sha256(env: Setup) -> None:
    import hashlib

    env.store().put(run_of(env.tmp, 1), "main")
    index = json.loads(show(env.bare, "baselines", "baselines/index.json"))
    entry = index["entries"][FP]["main"]["runs"][-1]
    assert entry["run_id"] == run_id(1)
    manifest = (env.data_root / FP / "main" / "manifest.json").read_bytes()
    assert entry["manifest_sha256"] == hashlib.sha256(manifest).hexdigest()


def test_a_fresh_store_reads_the_baseline_from_a_fresh_shallow_clone(env: Setup) -> None:
    run = run_of(env.tmp, 1)
    env.store().put(run, "main")
    back = env.store().get(FP, "main")
    assert back is not None
    assert unhashed(back.results).manifest == unhashed(run.results).manifest
    assert unhashed(back.results) == unhashed(run.results)


def test_an_unknown_fingerprint_or_an_empty_remote_is_none(env: Setup) -> None:
    assert env.store().get(FP, "main") is None  # the branch does not exist yet
    env.store().put(run_of(env.tmp, 1), "main")
    assert env.store().get("f" * 16, "main") is None
    assert env.store().get(FP, "nightly-b0") is None


def test_a_file_changed_after_put_is_a_store_error(env: Setup) -> None:
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    target = env.data_root / FP / "main" / "responses.jsonl.zst"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(StoreIntegrityError):
        store.get(FP, "main")


def test_a_consistently_rewritten_manifest_no_longer_matches_the_index(env: Setup) -> None:
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    path = env.data_root / FP / "main" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["promoted_at"] = "2030-01-01T00:00:00+00:00"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StoreIntegrityError, match="index"):
        store.get(FP, "main")


def test_an_index_entry_without_files_is_an_error_not_none(env: Setup) -> None:
    import shutil

    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    shutil.rmtree(env.data_root / FP / "main")
    with pytest.raises(StoreError, match="main"):
        store.get(FP, "main")


def test_a_missing_data_root_is_a_store_error_never_an_empty_store(env: Setup) -> None:
    import shutil

    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    shutil.rmtree(env.data_root)
    with pytest.raises(StoreError, match="data root"):
        store.get(FP, "main")
    with pytest.raises(StoreError, match="data root"):
        store.put(run_of(env.tmp, 2), "main")


def test_the_sentinel_check_protects_a_missing_mount(env: Setup) -> None:
    store = env.store(require_sentinel=True)
    with pytest.raises(StoreError, match="sentinel"):
        store.get(FP, "main")
    (env.data_root.parent / ".pruefstand-data-root").write_text("", encoding="utf-8")
    assert store.get(FP, "main") is None


def test_put_leaves_no_partial_directory(env: Setup) -> None:
    env.store().put(run_of(env.tmp, 1), "main")
    env.store().put(run_of(env.tmp, 2), "main")
    names = [p.name for p in (env.data_root / FP).rglob("*")]
    assert not [n for n in names if n.endswith((".partial", ".old", ".tmp"))]


def test_an_interrupted_put_keeps_the_previous_baseline_and_the_index(
    env: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    tip = git("rev-parse", "baselines", git_dir=env.bare).strip()

    def boom(*args: Any, **kwargs: Any) -> None:
        msg = "disk gone"
        raise OSError(msg)

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(StoreError):
        store.put(run_of(env.tmp, 2), "main")
    monkeypatch.undo()
    assert git("rev-parse", "baselines", git_dir=env.bare).strip() == tip
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


def test_a_refused_push_rolls_the_data_root_back(env: Setup) -> None:
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    tip = git("rev-parse", "baselines", git_dir=env.bare).strip()
    reject_pushes(env.bare)
    with pytest.raises(StoreError, match="push"):
        store.put(run_of(env.tmp, 2), "main")
    assert git("rev-parse", "baselines", git_dir=env.bare).strip() == tip
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)
    assert not (env.data_root / FP / "history" / run_id(2)).exists()
    assert not [p for p in (env.data_root / FP).iterdir() if p.name.endswith((".old", ".partial"))]


def test_a_push_that_fails_once_is_retried(env: Setup) -> None:
    reject_pushes(env.bare, times=1)
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    assert store.get(FP, "main") is not None


def test_two_puts_are_two_index_commits_and_the_branch_stays_small(env: Setup) -> None:
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    store.put(run_of(env.tmp, 2), "main")
    assert commit_count(env.bare, "baselines") == 2
    assert len(show(env.bare, "baselines", "baselines/index.json").encode()) < 64 * 1024
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(2)


def test_a_local_store_reads_the_same_baseline_for_the_restore_drill(env: Setup) -> None:
    run = run_of(env.tmp, 1)
    env.store().put(run, "main")
    back = LocalDirBaselineStore(env.data_root).get(FP, "main")
    assert back is not None
    assert unhashed(back.results) == unhashed(run.results)


def test_no_token_appears_on_any_git_command_line(
    env: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "ghp_" + "".join(chr(97 + (i * 7) % 26) for i in range(36))
    monkeypatch.setenv("PRUEFSTAND_BASELINES_TOKEN", secret)
    seen: list[list[str]] = []
    real = subprocess.run

    def spy(args: list[str], *a: Any, **kw: Any) -> Any:
        seen.append([str(x) for x in args])
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    store = env.store()
    store.put(run_of(env.tmp, 1), "main")
    assert store.get(FP, "main") is not None
    assert seen
    assert all(a[0] == "git" for a in seen)
    assert not any(secret in part for argv in seen for part in argv)
    assert secret not in show(env.bare, "baselines", "baselines/index.json")


def test_git_never_runs_through_a_shell(env: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs_seen: list[dict[str, Any]] = []
    real = subprocess.run

    def spy(args: list[str], *a: Any, **kw: Any) -> Any:
        kwargs_seen.append(kw)
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    env.store().put(run_of(env.tmp, 1), "main")
    assert kwargs_seen
    assert not any(kw.get("shell") for kw in kwargs_seen)
    assert all(kw.get("check") is True or "check" in kw for kw in kwargs_seen)
    assert all(kw.get("timeout") for kw in kwargs_seen)


def test_prune_updates_the_index_in_one_commit(env: Setup) -> None:
    store = env.store(clock=clock())
    for i in range(1, 24):
        store.put(run_of(env.tmp, i), "main")
    before = commit_count(env.bare, "baselines")
    removed = store.prune(keep=20, unused_days=90, now=START + timedelta(days=1))
    assert sorted(removed) == [f"{FP}/history/{run_id(i)}" for i in (1, 2, 3)]
    assert commit_count(env.bare, "baselines") == before + 1
    index = json.loads(show(env.bare, "baselines", "baselines/index.json"))
    runs = [e["run_id"] for e in index["entries"][FP]["main"]["runs"]]
    assert runs == [run_id(i) for i in range(4, 24)]
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(23)
    assert store.prune(keep=20, unused_days=90, now=START + timedelta(days=1)) == []
    assert commit_count(env.bare, "baselines") == before + 1


def test_prune_drops_a_stale_fingerprint_from_the_index(env: Setup) -> None:
    store = env.store(clock=clock())
    store.put(run_of(env.tmp, 1, eval_fingerprint="a" * 16), "main")
    store.prune(keep=20, unused_days=90, now=START + timedelta(days=100))
    index = json.loads(show(env.bare, "baselines", "baselines/index.json"))
    assert "a" * 16 not in index["entries"]
    assert not (env.data_root / ("a" * 16)).exists()
