"""Serialisation of one run directory: ``run.json``, ``results.parquet`` and the JSONL files."""

import json
import os
import stat
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord

MAX_FILE_BYTES = 128 * 1024 * 1024
"""Largest run file ``read_results`` accepts; a bigger file is refused before it is read."""
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

RESULT_COLUMNS = (
    "case_id", "base_id", "cluster_id", "tenant", "lang", "category", "perturbation", "split",
    "tags", "metric", "metric_version", "value", "status",
)  # fmt: skip
_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "case_id": pl.String,
    "base_id": pl.String,
    "cluster_id": pl.String,
    "tenant": pl.String,
    "lang": pl.String,
    "category": pl.String,
    "perturbation": pl.String,
    "split": pl.String,
    "tags": pl.List(pl.String),
    "metric": pl.String,
    "metric_version": pl.String,
    "value": pl.Float64,
    "status": pl.String,
}


def manifest_text(manifest: RunManifest) -> str:
    """Return ``run.json``: indent 2, sorted keys, UTF-8 text with a final newline."""
    data = manifest.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def results_frame(values: tuple[ScoredCase, ...]) -> pl.DataFrame:
    """One row per (case, metric) with the 13 columns of interfaces §8."""
    rows = [
        {
            "case_id": s.case.id,
            "base_id": s.case.base_id,
            "cluster_id": s.case.cluster_id,
            "tenant": s.case.tenant,
            "lang": s.case.lang.value,
            "category": s.case.category.value,
            "perturbation": s.case.perturbation,
            "split": s.case.split.value,
            "tags": list(s.case.tags),
            "metric": v.metric,
            "metric_version": v.metric_version,
            "value": v.value,
            "status": v.status.value,
        }
        for s in values
        for v in s.values
    ]
    return pl.DataFrame(
        {name: [row[name] for row in rows] for name in RESULT_COLUMNS}, schema=_SCHEMA
    )


def jsonl(models: tuple[CaseRecord, ...] | tuple[ScoredCase, ...]) -> str:
    """One JSON document per line (UTF-8 literals, no escaping of German text)."""
    return "".join(model.model_dump_json() + "\n" for model in models)


def write_files(root: Path, results: RunResults, llm_calls: pl.DataFrame | None) -> None:
    """Write every run file into the existing directory ``root``."""
    (root / "run.json").write_text(manifest_text(results.manifest), encoding="utf-8")
    results_frame(results.values).write_parquet(root / "results.parquet", compression="zstd")
    (root / "responses.jsonl").write_text(jsonl(results.records), encoding="utf-8")
    (root / "scored.jsonl").write_text(jsonl(results.values), encoding="utf-8")
    if llm_calls is not None:
        llm_calls.write_parquet(root / "llm_calls.parquet", compression="zstd")


def safe_error(exc: BaseException) -> str:
    """Describe ``exc`` without any value taken from file content (no pydantic ``input_value``)."""
    if isinstance(exc, ValidationError):
        items = exc.errors(include_url=False, include_context=False, include_input=False)
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in items[:5])
    if isinstance(exc, UnicodeDecodeError):
        return f"invalid UTF-8 at byte {exc.start}"
    if isinstance(exc, OSError):
        return type(exc).__name__
    return type(exc).__name__


def read_bounded(path: Path, limit: int) -> bytes:
    """Read a regular, non-symlink file of at most ``limit`` bytes.

    Raises:
        StoreError: The path is a symlink or not a regular file, is larger than ``limit``, or
            cannot be read. Nothing is followed and no special file is ever opened.
    """
    try:
        info = os.lstat(path)
    except OSError as exc:
        msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if stat.S_ISLNK(info.st_mode):
        msg = f"{path.name} in {path.parent} is a symlink; run files must be regular files"
        raise StoreError(msg)
    if not stat.S_ISREG(info.st_mode):
        msg = f"{path.name} in {path.parent} is not a regular file"
        raise StoreError(msg)
    if info.st_size > limit:
        msg = f"{path.name} in {path.parent} is {info.st_size} bytes, larger than the {limit} limit"
        raise StoreError(msg)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if len(data) > limit:
        msg = f"{path.name} in {path.parent} grew beyond the {limit} byte limit while reading"
        raise StoreError(msg)
    return data


def read_manifest(root: Path) -> RunManifest:
    """Parse ``run.json``.

    Raises:
        StoreError: The file is missing, special, too large, not JSON, or not a valid manifest.
    """
    data = read_bounded(root / "run.json", min(MAX_MANIFEST_BYTES, MAX_FILE_BYTES))
    try:
        return RunManifest.model_validate_json(data)
    except ValueError as exc:
        msg = f"cannot read run.json in {root}: {safe_error(exc)}"
        raise StoreError(msg) from exc


def read_results(root: Path) -> RunResults:
    """Parse a run directory into ``RunResults``, failing closed.

    Checks: the directory is named after ``manifest.run_id``; every file is a regular file within
    the size limit; case ids are unique and equal in ``responses.jsonl`` and ``scored.jsonl``; a
    complete run has exactly ``n_cases`` of them; ``results.parquet`` has the expected columns and
    row count (read from its footer) and equals the view derived from ``scored.jsonl``.

    Raises:
        StoreError: Any check fails or a file is missing or invalid. Messages never contain
            text taken from the files.
    """
    manifest = read_manifest(root)
    if root.name != manifest.run_id:
        msg = f"directory {root.name!r} does not match run_id {manifest.run_id!r} in run.json"
        raise StoreError(msg)
    records = tuple(_read_lines(root / "responses.jsonl", CaseRecord))
    values = tuple(_read_lines(root / "scored.jsonl", ScoredCase))
    ids = [s.case.id for s in values]
    if [r.case_id for r in records] != ids:
        msg = f"responses.jsonl and scored.jsonl disagree in {root}"
        raise StoreError(msg)
    if len(set(ids)) != len(ids):
        msg = f"duplicate case ids in {root}"
        raise StoreError(msg)
    if manifest.complete and len(values) != manifest.n_cases:
        msg = (
            f"complete run {manifest.run_id} has {len(values)} cases but n_cases={manifest.n_cases}"
        )
        raise StoreError(msg)
    if len(values) > manifest.n_cases:
        msg = (
            f"run {manifest.run_id} has more cases ({len(values)}) than n_cases={manifest.n_cases}"
        )
        raise StoreError(msg)
    _check_parquet(root / "results.parquet", values)
    return RunResults(manifest=manifest, records=records, values=values)


def _check_parquet(path: Path, values: tuple[ScoredCase, ...]) -> None:
    read_bounded(path, MAX_FILE_BYTES)  # regular file, size limit (content read again by polars)
    try:
        columns = tuple(pl.read_parquet_schema(path))
        if columns != RESULT_COLUMNS:
            msg = f"results.parquet in {path.parent} has unexpected columns"
            raise StoreError(msg)
        rows = int(pl.scan_parquet(path).select(pl.len()).collect().item())
        expected = sum(len(s.values) for s in values)
        if rows != expected:
            msg = (
                f"results.parquet in {path.parent} has {rows} rows, scored.jsonl implies {expected}"
            )
            raise StoreError(msg)
        frame = pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        msg = f"cannot read results.parquet in {path.parent}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if not frame.equals(results_frame(values)):
        msg = f"results.parquet and scored.jsonl disagree in {path.parent}"
        raise StoreError(msg)


def _read_lines[M: (CaseRecord, ScoredCase)](path: Path, model: type[M]) -> list[M]:
    data = read_bounded(path, MAX_FILE_BYTES)
    try:
        text = data.decode("utf-8")
        # split on "\n" only: str.splitlines() also cuts at U+2028, U+2029, U+0085, \x0b, \x0c ...
        return [model.model_validate_json(line) for line in text.split("\n") if line.strip()]
    except ValueError as exc:
        msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
        raise StoreError(msg) from exc
