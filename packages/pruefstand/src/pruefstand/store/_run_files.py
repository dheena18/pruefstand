"""Serialisation of one run directory: ``run.json``, ``results.parquet`` and the JSONL files."""

import hashlib
import io
import json
import os
import stat
from pathlib import Path
from typing import BinaryIO

import polars as pl

from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord
from pruefstand.store._safe_error import safe_error

MAX_FILE_BYTES = 128 * 1024 * 1024
"""Largest run file ``read_results`` accepts; a bigger file is refused before it is read."""
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PARQUET_BYTES = 64 * 1024 * 1024
"""``results.parquet`` is never decoded by ``read_results``; this only bounds the footer read."""

CHECKED_FILES = ("responses.jsonl", "results.parquet", "scored.jsonl")

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
    """Write every run file into the existing directory ``root``.

    The data files are written first; their SHA-256 values go into ``run.json``
    (``RunManifest.artifact_sha256``), which is written last.
    """
    results_frame(results.values).write_parquet(root / "results.parquet", compression="zstd")
    (root / "responses.jsonl").write_text(jsonl(results.records), encoding="utf-8")
    (root / "scored.jsonl").write_text(jsonl(results.values), encoding="utf-8")
    if llm_calls is not None:
        llm_calls.write_parquet(root / "llm_calls.parquet", compression="zstd")
    sums = {
        name: sha256_file(
            root / name, MAX_PARQUET_BYTES if name.endswith(".parquet") else MAX_FILE_BYTES
        )
        for name in CHECKED_FILES
    }
    manifest = results.manifest.model_copy(update={"artifact_sha256": sums})
    (root / "run.json").write_text(manifest_text(manifest), encoding="utf-8")


def _regular_stat(path: Path, limit: int) -> os.stat_result:
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
    return info


def _open_verified(path: Path, limit: int) -> BinaryIO:
    """Open a regular, non-symlink file of at most ``limit`` bytes; the caller closes it.

    The opened descriptor is checked again (regular file, same inode and device as the ``lstat``),
    so a path swapped for a symlink or another file in between is refused.
    """
    info = _regular_stat(path, limit)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        handle = os.fdopen(fd, "rb")
        opened = os.fstat(handle.fileno())
    except OSError as exc:
        msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if not stat.S_ISREG(opened.st_mode) or (opened.st_ino, opened.st_dev) != (
        info.st_ino,
        info.st_dev,
    ):
        handle.close()
        msg = f"{path.name} in {path.parent} changed while being opened"
        raise StoreError(msg)
    if opened.st_nlink > 1:
        handle.close()
        msg = f"{path.name} in {path.parent} is a hard link; run files must be plain files"
        raise StoreError(msg)
    return handle


def read_bounded(path: Path, limit: int) -> bytes:
    """Read a regular, non-symlink file of at most ``limit`` bytes (once).

    Raises:
        StoreError: Not a regular file, a symlink, larger than ``limit``, swapped, or unreadable.
    """
    with _open_verified(path, limit) as handle:
        try:
            data = handle.read(limit + 1)
        except OSError as exc:
            msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
            raise StoreError(msg) from exc
    if len(data) > limit:
        msg = f"{path.name} in {path.parent} grew beyond the {limit} byte limit while reading"
        raise StoreError(msg)
    return data


def sha256_file(path: Path, limit: int) -> str:
    """Return the SHA-256 of a regular file, streamed in 1 MiB chunks, without parsing it.

    Raises:
        StoreError: As ``read_bounded``.
    """
    digest = hashlib.sha256()
    total = 0
    with _open_verified(path, limit) as handle:
        try:
            while chunk := handle.read(1 << 20):
                total += len(chunk)
                if total > limit:
                    msg = f"{path.name} in {path.parent} grew beyond the {limit} byte limit"
                    raise StoreError(msg)
                digest.update(chunk)
        except OSError as exc:
            msg = f"cannot read {path.name} in {path.parent}: {safe_error(exc)}"
            raise StoreError(msg) from exc
    return digest.hexdigest()


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

    Order: ``run.json`` is parsed; the directory must be named after ``manifest.run_id``;
    ``manifest.artifact_sha256`` must name the three data files; the SHA-256 of ``results.parquet``
    (streamed, never decoded), ``responses.jsonl`` and ``scored.jsonl`` must match it *before*
    anything but ``run.json`` is parsed (``StoreIntegrityError`` otherwise). ``results.parquet``
    is never opened by a parser here: it is a derived view, and a hostile footer can abort a
    parser (rebuild it with ``results_frame`` if needed). Then case ids must be unique and
    equal in both jsonl files, and a complete run must have exactly ``n_cases`` of them.

    Raises:
        StoreError: Any check fails or a file is missing or invalid. Messages never contain
            text taken from the files.
    """
    manifest = read_manifest(root)
    if root.name != manifest.run_id:
        msg = f"directory name {root.name!r} does not match the run_id in run.json"
        raise StoreError(msg)
    expected = require_hashes(manifest, str(root))
    if sha256_file(root / "results.parquet", MAX_PARQUET_BYTES) != expected["results.parquet"]:
        msg = f"checksum mismatch for results.parquet in {root}"
        raise StoreIntegrityError(msg)
    responses = _read_hashed(root / "responses.jsonl", expected["responses.jsonl"])
    scored = _read_hashed(root / "scored.jsonl", expected["scored.jsonl"])
    return parse_results(manifest, responses, scored, str(root))


def require_hashes(manifest: RunManifest, where: str) -> dict[str, str]:
    """Return ``manifest.artifact_sha256`` after checking that it names the three data files.

    Raises:
        StoreIntegrityError: A data file has no recorded hash.
    """
    expected = manifest.artifact_sha256
    missing = [name for name in CHECKED_FILES if name not in expected]
    if missing:
        msg = f"run.json in {where} has no artifact_sha256 for {missing}"
        raise StoreIntegrityError(msg)
    return expected


def parse_results(manifest: RunManifest, responses: bytes, scored: bytes, where: str) -> RunResults:
    """Parse the two JSONL byte strings of a run whose hashes already matched.

    Case ids must be unique and equal in both files, and a complete run must have exactly
    ``n_cases`` of them. Callers hash and parse the *same* bytes (no re-open by name).

    Args:
        manifest: The parsed ``run.json``.
        responses: Content of ``responses.jsonl``.
        scored: Content of ``scored.jsonl``.
        where: Label for messages (a directory); never text from the files.

    Raises:
        StoreError: A line is invalid or the files disagree.
    """
    records = tuple(parse_lines(responses, CaseRecord, f"responses.jsonl in {where}"))
    values = tuple(parse_lines(scored, ScoredCase, f"scored.jsonl in {where}"))
    ids = [s.case.id for s in values]
    if [r.case_id for r in records] != ids:
        msg = f"responses.jsonl and scored.jsonl disagree in {where}"
        raise StoreError(msg)
    if len(set(ids)) != len(ids):
        msg = f"duplicate case ids in {where}"
        raise StoreError(msg)
    if manifest.complete and len(values) != manifest.n_cases:
        msg = f"complete run has {len(values)} cases but n_cases={manifest.n_cases} in {where}"
        raise StoreError(msg)
    if len(values) > manifest.n_cases:
        msg = f"run has more cases ({len(values)}) than n_cases={manifest.n_cases} in {where}"
        raise StoreError(msg)
    return RunResults(manifest=manifest, records=records, values=values)


def _read_hashed(path: Path, sha256: str) -> bytes:
    data = read_bounded(path, MAX_FILE_BYTES)
    if hashlib.sha256(data).hexdigest() != sha256:
        msg = f"checksum mismatch for {path.name} in {path.parent}"
        raise StoreIntegrityError(msg)
    return data


def parse_lines[M: (CaseRecord, ScoredCase)](data: bytes, model: type[M], label: str) -> list[M]:
    """Parse newline-separated JSON documents from bytes.

    Raises:
        StoreError: A line is not a valid ``model``; the message never contains file text.
    """
    try:
        # BytesIO iterates on b"\n" only (str.splitlines() also cuts at U+2028, U+0085, ...) and
        # pydantic validates the UTF-8 of each line, so no full-text copy is made.
        return [model.model_validate_json(line) for line in io.BytesIO(data) if line.strip()]
    except ValueError as exc:
        msg = f"cannot read {label}: {safe_error(exc)}"
        raise StoreError(msg) from exc
