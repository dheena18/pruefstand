"""Round-4 review: read_run never parses the untrusted parquet; checksums guard the files."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from testsupport.run_builders import make_results

from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store import _run_files
from pruefstand.store.artifacts import ArtifactStore

# Thrift compact FileMetaData: version=1, then field 2 (schema) as a list of 2^31-1 structs.
CRAFTED_FOOTER = bytes([0x15, 0x02, 0x19, 0xFC, 0xFF, 0xFF, 0xFF, 0xFF, 0x07, 0x00])


def crafted_parquet() -> bytes:
    """The 222-byte file class that aborted polars: padding, the crafted footer, its length."""
    tail = CRAFTED_FOOTER + len(CRAFTED_FOOTER).to_bytes(4, "little") + b"PAR1"
    return b"PAR1" + b"\x00" * (222 - 4 - len(tail)) + tail


def written(base: Path, count: int = 2) -> tuple[ArtifactStore, Path]:
    results = make_results(count)
    store = ArtifactStore(base)
    return store, store.write_run(
        RunArtifacts(results=results, root=base / results.manifest.run_id)
    )


def test_the_manifest_records_the_hashes_of_the_data_files(tmp_path: Path) -> None:
    _, path = written(tmp_path)
    sums = json.loads((path / "run.json").read_text(encoding="utf-8"))["artifact_sha256"]
    assert sorted(sums) == ["responses.jsonl", "results.parquet", "scored.jsonl"]
    assert all(len(v) == 64 for v in sums.values())
    assert not (path / "checksums.json").exists()


def test_tampered_values_with_a_valid_footer_and_a_stale_hash_are_refused(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    frame = pl.read_parquet(path / "results.parquet")
    frame.with_columns(value=pl.col("value") * 0.0).write_parquet(path / "results.parquet")
    with pytest.raises(StoreIntegrityError, match="checksum"):
        store.read_run(path)


def test_a_corrupted_parquet_is_refused_by_its_hash(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    data = bytearray((path / "results.parquet").read_bytes())
    data[len(data) // 2] ^= 0xFF
    (path / "results.parquet").write_bytes(bytes(data))
    with pytest.raises(StoreIntegrityError, match="checksum"):
        store.read_run(path)


@pytest.mark.parametrize("name", ["responses.jsonl", "scored.jsonl"])
def test_a_changed_jsonl_file_is_refused_by_its_hash(tmp_path: Path, name: str) -> None:
    store, path = written(tmp_path)
    data = (path / name).read_bytes().replace(b"Kleinbetriebe", b"Kleinbetriebx")
    (path / name).write_bytes(data)
    with pytest.raises(StoreIntegrityError, match="checksum"):
        store.read_run(path)


def test_a_missing_hash_field_is_refused(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    manifest = json.loads((path / "run.json").read_text(encoding="utf-8"))
    del manifest["artifact_sha256"]["results.parquet"]
    (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StoreIntegrityError, match="artifact_sha256"):
        store.read_run(path)
    manifest["artifact_sha256"] = {}
    (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StoreIntegrityError):
        store.read_run(path)


def test_a_valid_run_passes_and_mark_aborted_keeps_the_hashes(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    store.mark_aborted(path, "tunnel_lost: ssh exit 255")
    store.add_counts(path, {"model_reloads": 1})
    back = store.read_run(path).results.manifest
    assert back.stop_reason == "aborted"
    assert len(back.artifact_sha256) == 3


def test_the_crafted_footer_is_refused_by_hash_and_polars_is_never_called(tmp_path: Path) -> None:
    """A 222-byte-class footer that makes polars abort the process must not reach polars."""
    _, path = written(tmp_path / "store")
    (path / "results.parquet").write_bytes(crafted_parquet())
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        import polars as pl
        from pruefstand.core.errors import StoreError, StoreIntegrityError
        from pruefstand.store.artifacts import ArtifactStore

        def trap(*args, **kwargs):
            print("POLARS CALLED")
            sys.exit(3)

        names = ("read_parquet", "read_parquet_schema", "scan_parquet", "read_parquet_metadata")
        for name in names:
            setattr(pl, name, trap)
        try:
            ArtifactStore(Path({str(tmp_path / "store")!r})).read_run({str(path)!r})
        except StoreError as exc:
            print(exc)
            sys.exit(0)
        sys.exit(4)
        """
    )
    done = subprocess.run(  # noqa: S603  (fixed interpreter and script)
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "checksum" in done.stdout


def test_run_id_text_from_the_file_never_reaches_the_error(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    manifest = json.loads((path / "run.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "CANARY-RUNID"
    (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(StoreError) as info:
        store.read_run(path)
    assert "CANARY" not in str(info.value)


def test_a_regular_file_renamed_in_after_the_lstat_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.jsonl"
    target.write_bytes(b"{}\n")
    real = target.lstat()
    stale = SimpleNamespace(
        st_mode=real.st_mode, st_size=real.st_size, st_ino=real.st_ino + 1, st_dev=real.st_dev
    )
    real_lstat = os.lstat
    monkeypatch.setattr(
        os, "lstat", lambda p, **kw: stale if Path(p).name == "f.jsonl" else real_lstat(p)
    )
    with pytest.raises(StoreError, match="changed"):
        _run_files.read_bounded(target, 100)


def test_a_symlink_to_another_run_inside_the_root_is_refused(tmp_path: Path) -> None:
    store, first = written(tmp_path)
    other = make_results(2)
    other_manifest = other.manifest.model_copy(update={"run_id": "20990101T000000-abcdef"})
    other = other.model_copy(update={"manifest": other_manifest})
    second = store.write_run(RunArtifacts(results=other, root=tmp_path / other_manifest.run_id))
    (tmp_path / "alias").symlink_to(second, target_is_directory=True)
    with pytest.raises(StoreError, match="symlink"):
        store.read_run("alias")
    assert first != second


def test_update_uses_one_bounded_read_and_survives_a_missing_counts_key(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    data = json.loads((path / "run.json").read_text(encoding="utf-8"))
    del data["counts"]
    (path / "run.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StoreError):
        store.add_counts(path, {"model_reloads": 1})
