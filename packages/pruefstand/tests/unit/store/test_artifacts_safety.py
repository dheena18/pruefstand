"""Round-3 review: parquet bombs, key names in errors, special files and symlinked run dirs."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from testsupport.run_builders import make_results, refresh_hashes

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store import _run_files
from pruefstand.store import artifacts as artifacts_module
from pruefstand.store.artifacts import ArtifactStore


def written(base: Path) -> tuple[ArtifactStore, Path]:
    results = make_results(2)
    store = ArtifactStore(base)
    return store, store.write_run(
        RunArtifacts(results=results, root=base / results.manifest.run_id)
    )


def test_parquet_bomb_is_not_decoded(tmp_path: Path) -> None:
    """A tiny zstd file whose single value decodes to 60 MB must not be materialised."""
    _, path = written(tmp_path / "store")
    frame = pl.read_parquet(path / "results.parquet")
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "small.parquet")
    huge = frame.with_columns(
        tenant=pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit("a" * 60_000_000))
        .otherwise(pl.col("tenant"))
    )
    huge.write_parquet(path / "results.parquet", compression="zstd", row_group_size=10)
    assert (path / "results.parquet").stat().st_size < 1_000_000
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from pruefstand.store.artifacts import ArtifactStore
        from pruefstand.core.errors import StoreError
        store = ArtifactStore(Path({str(tmp_path / "store")!r}))
        def hwm_mb():
            lines = open('/proc/self/status').read().splitlines()
            return int([x for x in lines if x.startswith('VmHWM')][0].split()[1]) / 1024
        import polars as pl
        small = {str(tmp_path / "small.parquet")!r}
        pl.scan_parquet(small).select(pl.len()).collect()  # warm up polars' thread pool
        pl.read_parquet_schema(small)
        before = hwm_mb()
        try:
            store.read_run({str(path)!r})
        except StoreError:
            pass
        grown_mb = hwm_mb() - before
        print(grown_mb)
        sys.exit(0 if grown_mb < 30 else 1)
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


def test_parquet_body_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, path = written(tmp_path)

    def boom(*args: object, **kwargs: object) -> pl.DataFrame:
        msg = "parquet body decoded"
        raise AssertionError(msg)

    monkeypatch.setattr(pl, "read_parquet", boom)
    assert store.read_run(path).results.manifest.n_cases == 2


def _canary_line(extra: dict[str, object]) -> str:
    return json.dumps({"case_id": "law-0000", **extra}) + "\n"


@pytest.mark.parametrize("name", ["responses.jsonl", "scored.jsonl"])
def test_extra_key_names_in_jsonl_never_reach_the_error(tmp_path: Path, name: str) -> None:
    store, path = written(tmp_path)
    (path / name).write_text(_canary_line({"CANARY-sk-SECRETKEY": 1}), encoding="utf-8")
    refresh_hashes(path)
    with pytest.raises(StoreError) as info:
        store.read_run(path)
    assert "CANARY" not in str(info.value)
    assert "SECRETKEY" not in str(info.value)


def test_dict_key_names_in_run_json_never_reach_the_error(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    manifest = json.loads((path / "run.json").read_text(encoding="utf-8"))
    manifest["counts"] = {"CANARY-COUNTKEY": "x"}
    (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    for action in (
        lambda: store.read_run(path),
        lambda: store.add_counts(path, {"model_reloads": 1}),
    ):
        with pytest.raises(StoreError) as info:
            action()
        assert "CANARY" not in str(info.value)


def test_key_names_after_the_change_function_never_reach_the_error(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    with pytest.raises(StoreError) as info:
        store._update(path, lambda d: {**d, "counts": {"CANARY-AFTER-KEY": "x"}})
    assert "CANARY" not in str(info.value)


def test_parquet_column_names_never_reach_the_error(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    pl.read_parquet(path / "results.parquet").rename({"tenant": "CANARY-COLUMN"}).write_parquet(
        path / "results.parquet"
    )
    with pytest.raises(StoreError) as info:
        store.read_run(path)
    assert "CANARY" not in str(info.value)


def test_a_symlink_swapped_in_after_the_lstat_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, path = written(tmp_path / "store")
    secret = tmp_path / "secret.jsonl"
    secret.write_text("CANARY-RACE\n", encoding="utf-8")
    (path / "responses.jsonl").unlink()
    (path / "responses.jsonl").symlink_to(secret)
    real = os.lstat

    def lying(p: str | os.PathLike[str], **kw: object) -> os.stat_result:
        return Path(p).stat() if Path(p).name == "responses.jsonl" else real(p)  # follows the link

    monkeypatch.setattr(os, "lstat", lying)
    with pytest.raises(StoreError) as info:
        store.read_run(path)
    assert "CANARY" not in str(info.value)


def test_a_file_that_grows_after_the_size_check_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = tmp_path / "f.jsonl"
    big.write_bytes(b"x" * 500)
    real = big.lstat()
    fake = SimpleNamespace(st_mode=real.st_mode, st_size=10, st_ino=real.st_ino, st_dev=real.st_dev)
    real_lstat = os.lstat
    monkeypatch.setattr(
        os, "lstat", lambda p, **kw: fake if Path(p).name == "f.jsonl" else real_lstat(p)
    )
    with pytest.raises(StoreError, match="grew"):
        _run_files.read_bounded(big, 100)


def test_a_symlinked_run_directory_is_refused_and_not_written_through(tmp_path: Path) -> None:
    store, path = written(tmp_path)
    link = tmp_path / "20990101T000000-abcdef"
    link.symlink_to(path, target_is_directory=True)
    before = (path / "run.json").read_bytes()
    with pytest.raises(StoreError, match="symlink"):
        store.add_counts(link.name, {"model_reloads": 1})
    with pytest.raises(StoreError, match="symlink"):
        store.read_run(link)
    assert (path / "run.json").read_bytes() == before


def test_update_reads_run_json_with_the_bounded_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, path = written(tmp_path)
    (path / "run.json").write_text("{" + " " * 200, encoding="utf-8")
    monkeypatch.setattr(artifacts_module, "MAX_MANIFEST_BYTES", 100)
    with pytest.raises(StoreError, match="larger"):
        store.add_counts(path, {"model_reloads": 1})


def test_a_failing_hash_during_write_leaves_no_tmp_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: Path, limit: int) -> str:
        msg = "file is larger than the limit"
        raise StoreError(msg)

    monkeypatch.setattr(_run_files, "sha256_file", refuse)
    results = make_results(2)
    store = ArtifactStore(tmp_path)
    with pytest.raises(StoreError, match="larger"):
        store.write_run(RunArtifacts(results=results, root=tmp_path / results.manifest.run_id))
    assert list(tmp_path.iterdir()) == []


def test_a_parquet_over_the_read_cap_is_refused_at_write_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_run_files, "MAX_PARQUET_BYTES", 10)
    results = make_results(2)
    store = ArtifactStore(tmp_path)
    with pytest.raises(StoreError, match="larger"):
        store.write_run(RunArtifacts(results=results, root=tmp_path / results.manifest.run_id))
    assert list(tmp_path.iterdir()) == []
