"""``RunIndex``: DuckDB over run directories, never parsing an unverified parquet (T6.1 S6)."""

import itertools
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest
from testsupport.run_builders import refresh_hashes
from testsupport.store_support import run_id, run_of
from testsupport.timing import assert_scales_linearly

from pruefstand.core.errors import StoreError
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.run_index import RunIndex


def write_runs(root: Path, count: int = 3) -> list[Path]:
    store = ArtifactStore(root)
    paths = []
    for i in range(1, count + 1):
        run = run_of(root.parent, i, count=2)
        paths.append(store.write_run(run.model_copy(update={"root": root / run_id(i)})))
    return paths


def index_of(tmp_path: Path) -> RunIndex:
    return RunIndex(tmp_path / ".pruefstand" / "index.duckdb", tmp_path / "runs")


def count(index: RunIndex, table: str) -> int:
    return int(index.query(f"SELECT count(*) AS n FROM {table}")["n"][0])  # noqa: S608  (test table)


def test_three_runs_are_three_rows(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs")
    index = index_of(tmp_path)
    index.refresh()
    assert count(index, "runs") == 3
    assert count(index, "results") == 3 * 2 * 2  # runs x cases x metrics


def test_refresh_twice_is_idempotent(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs")
    index = index_of(tmp_path)
    index.refresh()
    index.refresh()
    assert count(index, "runs") == 3
    assert count(index, "results") == 12


def test_a_new_run_is_picked_up_and_old_rows_are_kept(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 2)
    index = index_of(tmp_path)
    index.refresh()
    ArtifactStore(tmp_path / "runs").write_run(
        run_of(tmp_path, 9).model_copy(update={"root": tmp_path / "runs" / run_id(9)})
    )
    index.refresh()
    assert count(index, "runs") == 3


def test_a_vanished_run_leaves_the_index(tmp_path: Path) -> None:
    paths = write_runs(tmp_path / "runs")
    index = index_of(tmp_path)
    index.refresh()
    shutil.rmtree(paths[0])
    index.refresh()
    assert count(index, "runs") == 2
    assert count(index, "results") == 8


def test_the_rows_carry_the_manifest_and_the_thirteen_result_columns(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 1)
    index = index_of(tmp_path)
    index.refresh()
    row = index.query("SELECT * FROM runs").row(0, named=True)
    assert row["run_id"] == run_id(1)
    assert row["complete"] is True
    assert row["stack"] == "live"
    results = index.query("SELECT * FROM results WHERE metric = 'context_recall'")
    assert {"case_id", "tenant", "lang", "metric", "value", "status", "tags"} <= set(
        results.columns
    )
    assert results["run_id"].unique().to_list() == [run_id(1)]


def test_query_returns_a_polars_frame(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 1)
    index = index_of(tmp_path)
    index.refresh()
    assert isinstance(index.query("SELECT 1 AS one"), pl.DataFrame)


def test_a_tampered_parquet_is_never_parsed_and_the_run_is_skipped(tmp_path: Path) -> None:
    paths = write_runs(tmp_path / "runs", 2)
    (paths[0] / "results.parquet").write_bytes(b"PAR1" + b"\x00" * 214 + b"PAR1")
    index = index_of(tmp_path)
    index.refresh()  # the hash no longer matches: nothing parses the file
    assert count(index, "runs") == 1
    assert index.query("SELECT run_id FROM runs")["run_id"].to_list() == [run_id(2)]


def test_a_rewritten_parquet_with_a_fixed_hash_is_not_parsed_either(tmp_path: Path) -> None:
    paths = write_runs(tmp_path / "runs", 1)
    (paths[0] / "results.parquet").write_bytes(b"PAR1" + b"\x00" * 214 + b"PAR1")
    refresh_hashes(paths[0])  # the attacker fixes run.json too: the rows come from scored.jsonl
    index = index_of(tmp_path)
    index.refresh()
    assert count(index, "results") == 4


def test_a_run_with_a_changed_scored_file_is_skipped(tmp_path: Path) -> None:
    paths = write_runs(tmp_path / "runs", 2)
    with (paths[1] / "scored.jsonl").open("ab") as handle:
        handle.write(b"\n")
    index = index_of(tmp_path)
    index.refresh()
    assert index.query("SELECT run_id FROM runs")["run_id"].to_list() == [run_id(1)]


def test_a_symlinked_run_directory_is_skipped(tmp_path: Path) -> None:
    paths = write_runs(tmp_path / "runs", 1)
    link = tmp_path / "runs" / run_id(5)
    link.symlink_to(paths[0], target_is_directory=True)
    index = index_of(tmp_path)
    index.refresh()
    assert count(index, "runs") == 1


def test_hidden_temporary_directories_are_ignored(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 1)
    (tmp_path / "runs" / f".{run_id(2)}.deadbeef.tmp").mkdir()
    index = index_of(tmp_path)
    index.refresh()
    assert count(index, "runs") == 1


def test_a_missing_runs_root_is_an_empty_index(tmp_path: Path) -> None:
    index = index_of(tmp_path)
    index.refresh()
    assert count(index, "runs") == 0


def test_a_query_cannot_read_files_or_write(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 1)
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    index = index_of(tmp_path)
    index.refresh()
    with pytest.raises(StoreError):
        index.query(f"SELECT * FROM read_csv('{secret}')")  # noqa: S608  (a test path)
    with pytest.raises(StoreError):
        index.query("DELETE FROM runs")
    with pytest.raises(StoreError):
        index.query(f"COPY runs TO '{tmp_path / 'out.csv'}'")
    assert count(index, "runs") == 1


def test_a_bad_query_is_a_store_error(tmp_path: Path) -> None:
    index = index_of(tmp_path)
    index.refresh()
    with pytest.raises(StoreError, match="query"):
        index.query("SELEKT nonsense")


def test_the_manifest_json_round_trips_through_the_runs_table(tmp_path: Path) -> None:
    write_runs(tmp_path / "runs", 1)
    index = index_of(tmp_path)
    index.refresh()
    stored = index.query("SELECT manifest FROM runs")["manifest"][0]
    assert json.loads(stored)["run_id"] == run_id(1)


def test_refresh_cost_is_linear_in_the_number_of_runs(tmp_path: Path) -> None:
    write_runs(tmp_path / "small", 4)
    write_runs(tmp_path / "big", 24)
    fresh = itertools.count()  # a new index file per run: a second refresh would be a no-op

    def refresher(runs: str) -> Callable[[], object]:
        return lambda: RunIndex(tmp_path / f"{runs}{next(fresh)}.duckdb", tmp_path / runs).refresh()

    # 6x the runs. The fixed cost of opening the index dominates (measured ratio ~1.5, linear
    # would be up to 6): the limit (~18) only guards against a rebuild per run, not a tight bound.
    assert_scales_linearly(refresher("small"), refresher("big"), scale=6, reps=3)
