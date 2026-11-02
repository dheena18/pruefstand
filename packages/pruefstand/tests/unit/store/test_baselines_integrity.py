"""Integrity, hostile names and links of the baseline store (T6.1 S4, hardening)."""

import hashlib
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import zstandard
from testsupport.store_support import FP, run_of

from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.factory import build_baseline_store, resolve_data_root

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


# --- integrity ---------------------------------------------------------------------------------


def current(tmp_path: Path) -> Path:
    return tmp_path / "baselines" / FP / "main"


def test_a_changed_stored_file_is_an_integrity_error(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    target = current(tmp_path) / "results.parquet"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(StoreIntegrityError, match=r"results\.parquet"):
        store.get(FP, "main")


def test_a_missing_stored_file_is_a_store_error(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    (current(tmp_path) / "scored.jsonl.zst").unlink()
    with pytest.raises(StoreError, match=r"scored\.jsonl\.zst"):
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
    with pytest.raises(StoreIntegrityError, match=r"scored\.jsonl"):
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
    with pytest.raises(StoreError, match="refusing to follow"):
        store.get(FP, "main")


def test_a_symlinked_fingerprint_directory_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    real = tmp_path / "elsewhere"
    Path(tmp_path / "baselines" / FP).rename(real)
    (tmp_path / "baselines" / FP).symlink_to(real, target_is_directory=True)
    with pytest.raises(StoreError, match="refusing to follow"):
        store.get(FP, "main")
    with pytest.raises(StoreError, match="refusing to follow"):
        store.put(run_of(tmp_path, 2), "main")


def test_a_symlinked_file_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    victim = tmp_path / "victim"
    victim.write_bytes((current(tmp_path) / "run.json").read_bytes())
    (current(tmp_path) / "run.json").unlink()
    (current(tmp_path) / "run.json").symlink_to(victim)
    with pytest.raises(StoreError, match="is a symlink"):
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
    monkeypatch.delenv("PRUEFSTAND_DATA_ROOT", raising=False)
    monkeypatch.delenv("PRUEFSTAND_HOME", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, str(tmp_path / value))
    cfg = BaselineStoreConfig(type="git_branch", repo="o/r")
    assert resolve_data_root(cfg) == tmp_path / expected


def test_an_explicit_data_root_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", str(tmp_path / "ignored"))
    cfg = BaselineStoreConfig(type="git_branch", repo="o/r", data_root=tmp_path / "mine")
    assert resolve_data_root(cfg) == tmp_path / "mine"


def test_a_hard_linked_file_is_refused(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    (tmp_path / "second-name").hardlink_to(current(tmp_path) / "run.json")
    with pytest.raises(StoreError, match="hard link"):
        store.get(FP, "main")


@pytest.mark.parametrize(
    "fp", ["ABCDEF0123456789", "0123456789abcde", "0123456789abcdef0", "ef-test"]
)
def test_only_sixteen_lowercase_hex_characters_are_a_fingerprint(tmp_path: Path, fp: str) -> None:
    with pytest.raises(StoreError, match="fingerprint"):
        store_at(tmp_path).get(fp, "main")
