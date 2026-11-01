"""Serialisation of one run directory: ``run.json``, ``results.parquet`` and the JSONL files."""

import json
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord

MAX_FILE_BYTES = 512 * 1024 * 1024
"""Largest run file ``read_results`` opens; bigger files are refused before reading."""
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


def _checked_size(path: Path, limit: int) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        msg = f"cannot read {path.name} in {path.parent}: {exc}"
        raise StoreError(msg) from exc
    if size > limit:
        msg = f"{path.name} in {path.parent} is {size} bytes, larger than the {limit} byte limit"
        raise StoreError(msg)


def read_manifest(root: Path) -> RunManifest:
    """Parse ``run.json``.

    Raises:
        StoreError: The file is missing, too large, not JSON, or not a valid manifest.
    """
    path = root / "run.json"
    _checked_size(path, min(MAX_MANIFEST_BYTES, MAX_FILE_BYTES))
    try:
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        msg = f"cannot read run.json in {root}: {exc}"
        raise StoreError(msg) from exc


def read_results(root: Path) -> RunResults:
    """Parse a run directory into ``RunResults``, failing closed.

    Checks: the directory is named after ``manifest.run_id``; every file is within the size
    limit; ``results.parquet`` parses and equals the view derived from ``scored.jsonl``;
    ``responses.jsonl`` and ``scored.jsonl`` list the same cases; a complete run has exactly
    ``n_cases`` of them.

    Raises:
        StoreError: Any check fails or a file is missing or invalid.
    """
    manifest = read_manifest(root)
    if root.name != manifest.run_id:
        msg = f"directory {root.name!r} does not match run_id {manifest.run_id!r} in run.json"
        raise StoreError(msg)
    records = tuple(_read_lines(root / "responses.jsonl", CaseRecord))
    values = tuple(_read_lines(root / "scored.jsonl", ScoredCase))
    if [r.case_id for r in records] != [s.case.id for s in values]:
        msg = f"responses.jsonl and scored.jsonl disagree in {root}"
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
    _checked_size(path, MAX_FILE_BYTES)
    try:
        frame = pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        msg = f"cannot read results.parquet in {path.parent}: {exc}"
        raise StoreError(msg) from exc
    if not frame.equals(results_frame(values)):
        msg = f"results.parquet and scored.jsonl disagree in {path.parent}"
        raise StoreError(msg)


def _read_lines[M: (CaseRecord, ScoredCase)](path: Path, model: type[M]) -> list[M]:
    _checked_size(path, MAX_FILE_BYTES)
    try:
        text = path.read_text(encoding="utf-8")
        # split on "\n" only: str.splitlines() also cuts at U+2028, U+2029, U+0085, \x0b, \x0c ...
        return [model.model_validate_json(line) for line in text.split("\n") if line.strip()]
    except (OSError, ValidationError, ValueError) as exc:
        msg = f"cannot read {path.name} in {path.parent}: {exc}"
        raise StoreError(msg) from exc
