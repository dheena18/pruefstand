"""Fail-closed reads, robust parsing and concurrency of ``ArtifactStore`` (review of PR 21)."""

import os
import threading
import time
from pathlib import Path

import polars as pl
import pytest
from testsupport.run_builders import make_results

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store import _run_files
from pruefstand.store.artifacts import ArtifactStore


def written(tmp_path: Path, count: int = 2) -> tuple[ArtifactStore, RunArtifacts, Path]:
    results = make_results(count)
    store = ArtifactStore(tmp_path)
    run = RunArtifacts(results=results, root=tmp_path / results.manifest.run_id)
    return store, run, store.write_run(run)


# --- fail-closed reads and robust parsing (review of PR 21) -------------------------------------


def test_unicode_line_separators_in_text_survive_the_round_trip(tmp_path: Path) -> None:
    results = make_results(2)
    odd = "Frist\u2028zwei\u2029drei\u0085vier\x0bfünf\x0csechs\x1csieben"
    record = results.records[0]
    assert record.response is not None
    records = (
        record.model_copy(update={"response": record.response.model_copy(update={"answer": odd})}),
        results.records[1],
    )
    case = results.values[0].case.model_copy(update={"question": odd})
    values = (results.values[0].model_copy(update={"case": case}), results.values[1])
    results = results.model_copy(update={"records": records, "values": values})
    store = ArtifactStore(tmp_path)
    path = store.write_run(RunArtifacts(results=results, root=tmp_path / results.manifest.run_id))
    assert store.read_run(path).results == results


def test_garbage_parquet_is_a_store_error(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    (path / "results.parquet").write_bytes(b"not parquet at all")
    with pytest.raises(StoreError, match=r"results\.parquet"):
        store.read_run(path)


def test_parquet_that_disagrees_with_scored_jsonl_is_a_store_error(tmp_path: Path) -> None:
    store, run, path = written(tmp_path)
    frame = pl.read_parquet(path / "results.parquet").with_columns(
        pl.col("metric").str.to_uppercase()
    )
    frame.write_parquet(path / "results.parquet")
    with pytest.raises(StoreError, match="disagree"):
        store.read_run(path)
    assert run is not None


def test_truncated_jsonl_files_are_store_errors(tmp_path: Path) -> None:
    for name in ("responses.jsonl", "scored.jsonl"):
        store, _, path = written(tmp_path / name)
        data = (path / name).read_bytes()
        (path / name).write_bytes(data[: len(data) // 2])
        with pytest.raises(StoreError):
            store.read_run(path)


def test_a_complete_run_with_missing_cases_is_a_store_error(tmp_path: Path) -> None:
    store, _, path = written(tmp_path, count=2)
    for name in ("responses.jsonl", "scored.jsonl"):
        lines = (path / name).read_text(encoding="utf-8").splitlines(keepends=True)
        (path / name).write_text("".join(lines[:1]), encoding="utf-8")
    frame = pl.read_parquet(path / "results.parquet").head(2)
    frame.write_parquet(path / "results.parquet")
    with pytest.raises(StoreError, match="n_cases"):
        store.read_run(path)


def test_a_renamed_run_directory_is_a_store_error(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    moved = path.rename(tmp_path / "20990101T000000-abcdef")
    with pytest.raises(StoreError, match="run_id"):
        store.read_run(moved)


def test_oversized_files_are_refused_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, path = written(tmp_path)
    monkeypatch.setattr(_run_files, "MAX_FILE_BYTES", 10)
    with pytest.raises(StoreError, match="larger than"):
        store.read_run(path)


def test_stale_tmp_directories_are_removed_on_write_but_fresh_ones_stay(tmp_path: Path) -> None:
    stale = tmp_path / ".old-run.abcd1234.tmp"
    fresh = tmp_path / ".new-run.abcd1234.tmp"
    stale.mkdir()
    fresh.mkdir()
    old = time.time() - 3 * 86400
    os.utime(stale, (old, old))
    written(tmp_path)
    assert not stale.exists()
    assert fresh.exists()


def test_concurrent_add_counts_keep_both_keys(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    errors: list[BaseException] = []

    def add(key: str) -> None:
        try:
            for i in range(20):
                store.add_counts(path, {key: i})
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=add, args=(k,)) for k in ("model_reloads", "upstream_errors")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    counts = store.read_run(path).results.manifest.counts
    assert counts["model_reloads"] == 19
    assert counts["upstream_errors"] == 19
