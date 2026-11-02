"""``RunIndex``: DuckDB tables ``runs`` and ``results`` over run directories (T6.1 S6, ADR-0003).

The files stay the source of truth; the index is derived and can be rebuilt any time. A run is
read with ``read_results`` (every data file is hashed before it is parsed) and the ``results``
rows are rebuilt from ``scored.jsonl`` with ``results_frame``: a ``results.parquet`` from disk is
never given to a parser, because a hostile footer can abort one.
"""

import stat
from pathlib import Path

import duckdb
import polars as pl

from pruefstand.core.errors import StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.run import RunManifest
from pruefstand.store._run_files import read_manifest, read_results, results_frame

_log = get_logger(__name__)
_RUNS = """CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, created_at TIMESTAMPTZ, eval_fingerprint VARCHAR,
    target_fingerprint VARCHAR, dataset_name VARCHAR, dataset_version VARCHAR, n_cases INTEGER,
    block INTEGER, judged_subset BOOLEAN, stratum VARCHAR, git_sha VARCHAR, git_ref VARCHAR,
    pr_number INTEGER, stack VARCHAR, workload VARCHAR, judge_mode VARCHAR, complete BOOLEAN,
    stop_reason VARCHAR, infra_error VARCHAR, judge_fallback BOOLEAN, judge_degraded BOOLEAN,
    judge_drift BOOLEAN, duration_s DOUBLE, cost_usd DOUBLE, scored_sha256 VARCHAR,
    manifest VARCHAR)"""
_RESULTS = """CREATE TABLE IF NOT EXISTS results (
    run_id VARCHAR, case_id VARCHAR, base_id VARCHAR, cluster_id VARCHAR, tenant VARCHAR,
    lang VARCHAR, category VARCHAR, perturbation VARCHAR, split VARCHAR, tags VARCHAR[],
    metric VARCHAR, metric_version VARCHAR, value DOUBLE, status VARCHAR)"""
_COLUMNS = (
    "run_id", "created_at", "eval_fingerprint", "target_fingerprint", "dataset_name",
    "dataset_version", "n_cases", "block", "judged_subset", "stratum", "git_sha", "git_ref",
    "pr_number", "stack", "workload", "judge_mode", "complete", "stop_reason", "infra_error",
    "judge_fallback", "judge_degraded", "judge_drift", "duration_s", "cost_usd", "scored_sha256",
    "manifest",
)  # fmt: skip


def _row(manifest: RunManifest) -> tuple[object, ...]:
    data = manifest.model_dump(mode="python")
    return (
        *(data[name] for name in _COLUMNS[:-3]),
        manifest.cost.usd,
        manifest.artifact_sha256.get("scored.jsonl"),
        manifest.model_dump_json(),
    )


class RunIndex:
    """A DuckDB database with one row per run and one row per (run, case, metric).

    Args:
        db_path: The DuckDB file (e.g. ``.pruefstand/index.duckdb``); its directory is created.
        runs_root: Directory with ``<run_id>/`` run directories.
    """

    def __init__(self, db_path: Path, runs_root: Path) -> None:
        self._db = db_path
        self._root = runs_root

    def refresh(self) -> None:
        """Bring the tables in line with the run directories; running it twice changes nothing.

        New and changed runs (by the ``scored.jsonl`` hash in ``run.json``) are read and verified;
        runs that vanished are removed. A run that fails verification (checksum, size, symlink,
        invalid files) is skipped with a warning and does not stop the others.

        Raises:
            StoreError: The database cannot be opened or written.
        """
        self._db.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = duckdb.connect(str(self._db))
        except duckdb.Error as exc:
            msg = f"cannot open the run index {self._db}: {exc}"
            raise StoreError(msg) from exc
        try:
            con.execute(_RUNS)
            con.execute(_RESULTS)
            known = dict(con.execute("SELECT run_id, scored_sha256 FROM runs").fetchall())
            seen = self._sync(con, known)
            for gone in sorted(set(known) - seen):
                self._delete(con, gone)
        except duckdb.Error as exc:
            msg = f"cannot update the run index: {exc}"
            raise StoreError(msg) from exc
        finally:
            con.close()

    def query(self, sql: str) -> pl.DataFrame:
        """Run read-only SQL against ``runs`` and ``results``.

        The connection is read-only and cannot reach files (``enable_external_access`` is off), so
        a query cannot read ``/etc`` or write a file.

        Args:
            sql: One SQL statement.

        Returns:
            The result as a polars frame.

        Raises:
            StoreError: The index was never built, or the statement failed.
        """
        if not self._db.is_file():
            msg = f"the run index {self._db} does not exist; call refresh() first"
            raise StoreError(msg)
        try:
            con = duckdb.connect(
                str(self._db), read_only=True, config={"enable_external_access": False}
            )
            try:
                relation: object = con.sql(sql)  # a statement without a result gives None
                if not isinstance(relation, duckdb.DuckDBPyRelation):
                    return pl.DataFrame()
                return pl.DataFrame(relation.to_arrow_table())
            finally:
                con.close()
        except duckdb.Error as exc:
            msg = f"query failed: {exc}"
            raise StoreError(msg) from exc

    def _sync(self, con: duckdb.DuckDBPyConnection, known: dict[str, str | None]) -> set[str]:
        seen: set[str] = set()
        if not self._root.is_dir():
            return seen
        for directory in sorted(self._root.iterdir()):
            if directory.name.startswith("."):
                continue
            try:
                self._ingest(con, directory, known, seen)
            except StoreError as exc:
                _log.warning("run_index_skipped", directory=directory.name, error=str(exc))
        return seen

    def _ingest(
        self,
        con: duckdb.DuckDBPyConnection,
        directory: Path,
        known: dict[str, str | None],
        seen: set[str],
    ) -> None:
        if stat.S_ISLNK(directory.lstat().st_mode) or not directory.is_dir():
            msg = "not a real run directory"
            raise StoreError(msg)
        manifest = read_manifest(directory)
        if directory.name != manifest.run_id:
            msg = "directory name differs from the run_id in run.json"
            raise StoreError(msg)
        sha = manifest.artifact_sha256.get("scored.jsonl")
        if sha is not None and known.get(manifest.run_id) == sha:
            seen.add(manifest.run_id)
            return
        results = read_results(directory)  # hashes before it parses; the parquet is never parsed
        frame = results_frame(results.values).with_columns(
            pl.lit(results.manifest.run_id).alias("run_id")
        )
        placeholders = ", ".join("?" for _ in _COLUMNS)
        con.execute("BEGIN")
        try:
            self._delete(con, manifest.run_id)
            con.execute(f"INSERT INTO runs VALUES ({placeholders})", _row(results.manifest))  # noqa: S608
            con.register("run_frame", frame.select("run_id", *frame.columns[:-1]))
            con.execute("INSERT INTO results SELECT * FROM run_frame")
            con.unregister("run_frame")
        except duckdb.Error:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        seen.add(manifest.run_id)

    @staticmethod
    def _delete(con: duckdb.DuckDBPyConnection, run_id: str) -> None:
        con.execute("DELETE FROM results WHERE run_id = ?", [run_id])
        con.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
