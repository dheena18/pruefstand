"""``LocalDirBaselineStore``: layout, refs, atomic writes, integrity and hardening (T6.1 S4)."""

import hashlib
import io
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import zstandard
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.factory import build_baseline_store
from testsupport.run_builders import unhashed
from testsupport.store_support import FP, release_run, run_id, run_of

from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.models.run import RunArtifacts

START = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def clock() -> Callable[[], datetime]:
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return START + timedelta(seconds=state["n"])

    return tick


def store_at(tmp_path: Path) -> LocalDirBaselineStore:
    return LocalDirBaselineStore(tmp_path / "baselines", clock=clock())


def block_run(tmp_path: Path, block: int, index: int = 1, **changes: Any) -> RunArtifacts:
    return run_of(tmp_path, index, block=block, eval_fingerprint=f"{block}" * 16, **changes)


def test_put_then_get_by_fingerprint_and_ref(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    run = run_of(tmp_path)
    store.put(run, "main")
    back = store.get(FP, "main")
    assert back is not None
    assert unhashed(back.results) == unhashed(run.results)
    assert back.root == tmp_path / "baselines" / FP / "main"
    assert back.results.manifest.artifact_sha256  # the stored run.json carries the hashes


def test_the_default_ref_is_main(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path))
    assert store.get(FP) is not None


def test_the_current_baseline_directory_holds_five_files_and_history_two_plus_manifest(
    tmp_path: Path,
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    base = tmp_path / "baselines" / FP
    assert sorted(p.name for p in (base / "main").iterdir()) == [
        "manifest.json",
        "responses.jsonl.zst",
        "results.parquet",
        "run.json",
        "scored.jsonl.zst",
    ]
    assert sorted(p.name for p in (base / "history" / run_id(1)).iterdir()) == [
        "manifest.json",
        "results.parquet",
        "run.json",
    ]


def test_the_manifest_lists_a_sha256_for_every_stored_file(tmp_path: Path) -> None:
    store_at(tmp_path).put(run_of(tmp_path), "main")
    directory = tmp_path / "baselines" / FP / "main"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {
        "run.json", "results.parquet", "responses.jsonl.zst", "scored.jsonl.zst",
    }  # fmt: skip
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


def test_main_and_the_block_refs_are_isolated(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    for block in range(3):
        store.put(block_run(tmp_path, block, index=10 + block), f"nightly-b{block}")
        store.put(block_run(tmp_path, block, index=20 + block), f"release-b{block}")
    assert store.get(FP, "main") is not None
    for block in range(3):
        fp = f"{block}" * 16
        nightly, release = store.get(fp, f"nightly-b{block}"), store.get(fp, f"release-b{block}")
        assert nightly is not None
        assert release is not None
        assert nightly.results.manifest.run_id == run_id(10 + block)
        assert release.results.manifest.run_id == run_id(20 + block)
        assert store.get(fp, "main") is None
        assert store.get(fp, f"nightly-b{(block + 1) % 3}") is None


@pytest.mark.parametrize(
    "ref", ["release", "nightly-b3", "release-b3", "foo", "", "../main", "main/x"]
)
def test_an_unknown_ref_is_a_store_error(tmp_path: Path, ref: str) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match="ref"):
        store.get(FP, ref)
    with pytest.raises(StoreError, match="ref"):
        store.put(run_of(tmp_path), ref)


def test_a_block_ref_needs_a_run_of_that_block(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match="block"):
        store.put(run_of(tmp_path), "nightly-b1")
    with pytest.raises(StoreError, match="block"):
        store.put(block_run(tmp_path, 2), "nightly-b1")
    with pytest.raises(StoreError, match="block"):
        store.put(block_run(tmp_path, 1), "main")
    with pytest.raises(StoreError, match="block"):
        store.put(release_run(tmp_path), "release-b1")  # the raw release run is not a projection


def test_an_unknown_fingerprint_is_none(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    assert store.get("f" * 16, "main") is None
    assert store_at(tmp_path / "other").get(FP) is None


def test_two_puts_return_the_newer_and_keep_both(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    store.put(run_of(tmp_path, 2), "main")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(2)
    assert sorted(p.name for p in (tmp_path / "baselines" / FP / "history").iterdir()) == [
        run_id(1),
        run_id(2),
    ]


def test_putting_the_same_run_twice_is_fine(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    store.put(run_of(tmp_path, 1), "main")
    assert store.get(FP, "main") is not None


@pytest.mark.parametrize("failing_call", [1, 2])
def test_a_failed_rename_leaves_the_previous_baseline_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_call: int
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    real = os.rename
    calls = {"n": 0}

    def flaky(src: Any, dst: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] >= failing_call:
            msg = "disk gone"
            raise OSError(msg)
        real(src, dst, **kwargs)

    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(StoreError, match="cannot"):
        store.put(run_of(tmp_path, 2), "main")
    monkeypatch.undo()
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)
    leftovers = [p.name for p in (tmp_path / "baselines" / FP).iterdir()]
    assert not [n for n in leftovers if n.endswith((".partial", ".old"))]
    assert not (tmp_path / "baselines" / FP / "history" / run_id(2)).exists()


def test_readers_ignore_partial_directories(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    junk = tmp_path / "baselines" / FP / "main.abcd1234.partial"
    junk.mkdir()
    (junk / "run.json").write_text("{not json", encoding="utf-8")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


def test_a_missing_current_directory_after_an_interrupted_swap_is_an_error_not_none(
    tmp_path: Path,
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    base = tmp_path / "baselines" / FP
    (base / "main").rename(base / "main.cafe0123.old")
    with pytest.raises(StoreError, match="interrupted"):
        store.get(FP, "main")


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False, "stop_reason": "aborted"},
        {"complete": False, "stop_reason": "budget_exceeded"},
    ],
)
def test_an_incomplete_run_is_refused_and_the_store_is_unchanged(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    with pytest.raises(StoreError, match="complete"):
        store.put(run_of(tmp_path, 2, **changes), "main")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"judge_fallback": True}, "judge fallback"),
        ({"judge_drift": True}, "judge_drift"),
        ({"judge_degraded": True}, "judge_degraded"),
        (
            {"stop_reason": "aborted", "complete": False, "infra_error": "tunnel_lost: x"},
            "complete",
        ),
        ({"counts": {"ok": 2, "judge_truncated": 2}, "judged_cases": 2}, "judge_truncated"),
    ],
)
def test_a_flagged_run_is_never_promoted(
    tmp_path: Path, changes: dict[str, Any], word: str
) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match=word):
        store.put(run_of(tmp_path, 1, **changes), "main")
    assert store.get(FP, "main") is None


def test_a_few_truncations_do_not_block_a_promotion(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    run = run_of(tmp_path, 1, counts={"ok": 2, "judge_truncated": 1}, judged_cases=100)
    store.put(run, "main")
    assert store.get(FP, "main") is not None


def test_the_truncation_share_is_the_one_of_the_gate() -> None:
    from pruefstand.store.promote import JUDGE_TRUNCATED_SHARE

    from pruefstand.pipeline.gate import _TRUNCATED_SHARE

    assert JUDGE_TRUNCATED_SHARE == _TRUNCATED_SHARE


# --- integrity ---------------------------------------------------------------------------------


def current(tmp_path: Path) -> Path:
    return tmp_path / "baselines" / FP / "main"


def test_a_changed_stored_file_is_an_integrity_error(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    target = current(tmp_path) / "results.parquet"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(StoreIntegrityError, match="results.parquet"):
        store.get(FP, "main")


def test_a_missing_stored_file_is_a_store_error(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    (current(tmp_path) / "scored.jsonl.zst").unlink()
    with pytest.raises(StoreError, match="scored.jsonl.zst"):
        store.get(FP, "main")


def rewrite(directory: Path, name: str, data: bytes) -> None:
    """Replace a file and fix manifest.json, as an attacker with write access could."""
    (directory / name).write_bytes(data)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(data).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_a_consistent_manifest_does_not_hide_a_changed_inner_hash(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    directory = current(tmp_path)
    lines = zstandard.ZstdDecompressor().decompress((directory / "scored.jsonl.zst").read_bytes())
    rewrite(directory, "scored.jsonl.zst", zstandard.ZstdCompressor().compress(lines + b"\n"))
    with pytest.raises(StoreIntegrityError, match="scored.jsonl"):
        store.get(FP, "main")


def test_a_hostile_parquet_with_matching_hashes_is_never_parsed(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    directory = current(tmp_path)
    hostile = b"PAR1" + b"\x00" * 214 + b"PAR1"  # 222 bytes: a crafted footer aborts a parser
    rewrite(directory, "results.parquet", hostile)
    run_json = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    run_json["artifact_sha256"]["results.parquet"] = hashlib.sha256(hostile).hexdigest()
    rewrite(directory, "run.json", json.dumps(run_json).encode())
    back = store.get(FP, "main")  # no parser ever sees it
    assert back is not None


def test_a_decompression_bomb_is_refused_without_inflating_it(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    directory = current(tmp_path)
    bomb = io.BytesIO()
    with zstandard.ZstdCompressor(level=1).stream_writer(bomb, closefd=False) as writer:
        chunk = b"\x00" * (1 << 20)
        for _ in range(160):  # 160 MiB > the 128 MiB cap, a few hundred KiB compressed
            writer.write(chunk)
    rewrite(directory, "responses.jsonl.zst", bomb.getvalue())
    with pytest.raises(StoreError, match="larger than"):
        store.get(FP, "main")


def test_an_oversized_manifest_json_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    (current(tmp_path) / "manifest.json").write_bytes(b" " * (2 * 1024 * 1024))
    with pytest.raises(StoreError, match="larger than"):
        store.get(FP, "main")


def test_garbage_in_a_stored_file_never_leaks_its_text(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    (current(tmp_path) / "manifest.json").write_text('{"secret-looking-key": 1}', encoding="utf-8")
    with pytest.raises(StoreError) as excinfo:
        store.get(FP, "main")
    assert "secret-looking-key" not in str(excinfo.value)


def test_the_manifest_must_name_the_directory_it_sits_in(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    store.put(block_run(tmp_path, 1, index=3), "nightly-b1")
    other = tmp_path / "baselines" / ("1" * 16) / "nightly-b1"
    moved = tmp_path / "baselines" / FP / "nightly-b1"
    moved.parent.mkdir(exist_ok=True)
    Path(other).rename(moved)  # a baseline copied under a fingerprint it does not belong to
    with pytest.raises(StoreError, match="does not belong"):
        store.get(FP, "nightly-b1")


# --- hardening: names and links ----------------------------------------------------------------


@pytest.mark.parametrize(
    "fp", ["../x", "a/b", "..", ".", "", "a" * 65, "x y", "ü", "-rf", "a\x00b"]
)
def test_a_hostile_fingerprint_is_refused_everywhere(tmp_path: Path, fp: str) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match="fingerprint"):
        store.get(fp, "main")
    run = run_of(tmp_path, 1, eval_fingerprint=fp)
    with pytest.raises(StoreError, match="fingerprint"):
        store.put(run, "main")
    assert not (tmp_path / "x").exists()


def test_a_hostile_run_id_cannot_leave_the_history_directory(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    run = run_of(tmp_path, 1, run_id="../../escape")
    with pytest.raises(StoreError, match="run id"):
        store.put(run, "main")
    assert not (tmp_path / "escape").exists()


def test_a_symlinked_baseline_directory_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    real = tmp_path / "elsewhere"
    Path(current(tmp_path)).rename(real)
    current(tmp_path).symlink_to(real, target_is_directory=True)
    with pytest.raises(StoreError, match="symlink"):
        store.get(FP, "main")


def test_a_symlinked_fingerprint_directory_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    real = tmp_path / "elsewhere"
    Path(tmp_path / "baselines" / FP).rename(real)
    (tmp_path / "baselines" / FP).symlink_to(real, target_is_directory=True)
    with pytest.raises(StoreError, match="symlink"):
        store.get(FP, "main")
    with pytest.raises(StoreError, match="symlink"):
        store.put(run_of(tmp_path, 2), "main")


def test_a_symlinked_file_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    victim = tmp_path / "victim"
    victim.write_bytes((current(tmp_path) / "run.json").read_bytes())
    (current(tmp_path) / "run.json").unlink()
    (current(tmp_path) / "run.json").symlink_to(victim)
    with pytest.raises(StoreError, match="symlink"):
        store.get(FP, "main")


def test_no_token_ever_lands_in_a_stored_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "ghp_" + "".join(chr(97 + i % 26) for i in range(36))
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "PRUEFSTAND_BASELINES_TOKEN", "DASHBOARD_DATA_PAT"):
        monkeypatch.setenv(name, secret)
    store_at(tmp_path).put(run_of(tmp_path), "main")
    for path in (tmp_path / "baselines").rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_build_baseline_store_makes_a_local_store(tmp_path: Path) -> None:
    store = build_baseline_store(BaselineStoreConfig(type="local_dir", path=tmp_path))
    assert isinstance(store, LocalDirBaselineStore)


def test_build_baseline_store_makes_a_git_store_without_running_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        msg = "git must not run at construction"
        raise AssertionError(msg)

    monkeypatch.setattr("subprocess.run", boom)
    cfg = BaselineStoreConfig(type="git_branch", repo="o/r", data_root=tmp_path)
    assert isinstance(build_baseline_store(cfg), GitBranchBaselineStore)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"PRUEFSTAND_DATA_ROOT": "DATA"}, "DATA/baselines"),
        ({"PRUEFSTAND_HOME": "HOME"}, "HOME/baselines"),
    ],
)
def test_the_default_data_root_follows_d209(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    from pruefstand.store.factory import resolve_data_root

    monkeypatch.delenv("PRUEFSTAND_DATA_ROOT", raising=False)
    monkeypatch.delenv("PRUEFSTAND_HOME", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, str(tmp_path / value))
    cfg = BaselineStoreConfig(type="git_branch", repo="o/r")
    assert resolve_data_root(cfg) == tmp_path / expected


def test_an_explicit_data_root_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pruefstand.store.factory import resolve_data_root

    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", str(tmp_path / "ignored"))
    cfg = BaselineStoreConfig(type="git_branch", repo="o/r", data_root=tmp_path / "mine")
    assert resolve_data_root(cfg) == tmp_path / "mine"
