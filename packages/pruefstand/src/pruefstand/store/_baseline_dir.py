"""The on-disk layout of baselines (data root) and the verified reader.

``<root>/<fingerprint>/<ref>/`` holds the current baseline (``run.json``, ``results.parquet``,
``responses.jsonl.zst``, ``scored.jsonl.zst``, ``manifest.json``) and
``<root>/<fingerprint>/history/<run_id>/`` one immutable copy of ``run.json``, ``results.parquet``
and ``manifest.json`` per promotion (gpu-cluster.md §9). Writing is in ``_baseline_write``;
readers ignore ``*.partial`` and ``*.old``.

Reading hashes and parses the *same* in-memory bytes: ``manifest.json`` pins every stored file,
``run.json`` pins the uncompressed data files, and ``results.parquet`` is hashed but never parsed.
"""

import hashlib
import io
import json
import os
import re
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import zstandard
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.run import RunArtifacts, RunManifest
from pruefstand.store._run_files import (
    MAX_FILE_BYTES,
    MAX_PARQUET_BYTES,
    parse_results,
    read_bounded,
    require_hashes,
)
from pruefstand.store._safe_error import safe_error
from pruefstand.store.baseline_index import (
    validate_fingerprint,
    validate_ref,
    validate_run_id,
)

_log = get_logger(__name__)
MANIFEST = "manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024
CURRENT_FILES = ("run.json", "results.parquet", "responses.jsonl.zst", "scored.jsonl.zst")
HISTORY_FILES = ("run.json", "results.parquet")
_COMPRESSED = {"responses.jsonl.zst": "responses.jsonl", "scored.jsonl.zst": "scored.jsonl"}
_LEFTOVER = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\.[0-9a-f]{8}\.(?P<kind>partial|old)$")


class BaselineManifest(BaseModel):
    """``manifest.json`` of a baseline directory: what was promoted and the SHA-256 of each file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    run_id: str
    eval_fingerprint: str
    ref: str
    promoted_at: AwareDatetime
    git_sha: str | None
    files: dict[str, str]


def manifest_bytes(manifest: BaselineManifest) -> bytes:
    """Serialise a baseline manifest (indent 2, sorted keys, final newline)."""
    data = manifest.model_dump(mode="json")
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def parse_manifest(data: bytes, where: str) -> BaselineManifest:
    """Parse and validate ``manifest.json`` bytes.

    Raises:
        StoreError: Invalid manifest, or a name that is no safe path component.
    """
    try:
        manifest = BaselineManifest.model_validate_json(data)
    except ValidationError as exc:
        msg = f"cannot read manifest.json in {where}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    validate_fingerprint(manifest.eval_fingerprint)
    validate_run_id(manifest.run_id)
    validate_ref(manifest.ref)
    return manifest


def real_dir(path: Path, *, missing_ok: bool = False) -> bool:
    """Whether ``path`` is a real directory; a symlink or another file type is an error.

    Raises:
        StoreError: ``path`` is a symlink, not a directory, or missing (unless ``missing_ok``).
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return False
        msg = f"{path} does not exist"
        raise StoreError(msg) from None
    except OSError as exc:
        msg = f"cannot inspect {path}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if stat.S_ISLNK(info.st_mode):
        msg = f"{path} is a symlink; refusing to follow it"
        raise StoreError(msg)
    if not stat.S_ISDIR(info.st_mode):
        msg = f"{path} is not a directory"
        raise StoreError(msg)
    return True


def remove_tree(path: Path) -> None:
    """Delete a real directory tree (never a symlink; never anything a link points to).

    Raises:
        StoreError: ``path`` is a symlink or not a directory, or deletion failed.
    """
    real_dir(path)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        msg = f"cannot delete {path}: {exc}"
        raise StoreError(msg) from exc


def zstd_compress(data: bytes) -> bytes:
    """Compress ``data`` (level 3, a content-size frame header)."""
    return zstandard.ZstdCompressor(level=3).compress(data)


def zstd_decompress(data: bytes, name: str, limit: int = MAX_FILE_BYTES) -> bytes:
    """Decompress one zstd frame, refusing to inflate beyond ``limit`` bytes.

    Raises:
        StoreError: Not a zstd frame, or it expands past ``limit`` (a decompression bomb).
    """
    chunks: list[bytes] = []
    total = 0
    try:
        reader = zstandard.ZstdDecompressor(max_window_size=1 << 27).stream_reader(io.BytesIO(data))
        while chunk := reader.read(1 << 20):
            total += len(chunk)
            if total > limit:
                msg = f"{name} expands to more than the {limit} byte limit (larger than allowed)"
                raise StoreError(msg)
            chunks.append(chunk)
    except zstandard.ZstdError as exc:
        msg = f"cannot decompress {name}: {type(exc).__name__}"
        raise StoreError(msg) from exc
    return b"".join(chunks)


def read_baseline_manifest(directory: Path) -> BaselineManifest:
    """Read ``manifest.json`` of a baseline or history directory (bounded, no symlinks)."""
    return parse_manifest(read_bounded(directory / MANIFEST, MAX_MANIFEST_BYTES), str(directory))


def read_baseline(
    root: Path, fingerprint: str, ref: str, *, expected_manifest_sha256: str | None = None
) -> RunArtifacts | None:
    """Read and verify the current baseline of ``(fingerprint, ref)``.

    Args:
        root: The data root.
        fingerprint: ``eval_fingerprint`` (validated here).
        ref: One of the refs (validated here).
        expected_manifest_sha256: SHA-256 of ``manifest.json`` pinned by ``index.json`` (git
            store); None for the local store.

    Returns:
        The run, with ``root`` set to the baseline directory; None when there is no such baseline.

    Raises:
        StoreError: A name is unsafe, a path is a symlink, a file is missing, oversized or invalid,
            the baseline does not belong under this fingerprint and ref, or a promotion was
            interrupted (``<ref>.<hex>.old`` without ``<ref>``).
        StoreIntegrityError: A hash differs from ``manifest.json`` / ``run.json`` / the index.
    """
    validate_fingerprint(fingerprint)
    validate_ref(ref)
    base = root / fingerprint
    if not real_dir(base, missing_ok=True):
        return None
    current = base / ref
    if not real_dir(current, missing_ok=True):
        if any(m.group("name") == ref and m.group("kind") == "old" for m in leftovers(base)):
            msg = (
                f"the promotion of {fingerprint}/{ref} was interrupted; restore the .old directory"
            )
            raise StoreError(msg)
        return None
    return _verified(current, fingerprint, ref, expected_manifest_sha256)


def leftovers(base: Path) -> Iterator[re.Match[str]]:
    for entry in base.iterdir():
        match = _LEFTOVER.match(entry.name)
        if match:
            yield match


def _verified(
    current: Path, fingerprint: str, ref: str, expected_sha256: str | None
) -> RunArtifacts:
    where = f"{fingerprint}/{ref}"
    raw = read_bounded(current / MANIFEST, MAX_MANIFEST_BYTES)
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        msg = f"manifest.json of {where} does not match the baseline index"
        raise StoreIntegrityError(msg)
    manifest = parse_manifest(raw, where)
    if manifest.eval_fingerprint != fingerprint or manifest.ref != ref:
        msg = f"the baseline in {where} does not belong there"
        raise StoreError(msg)
    stored: dict[str, bytes] = {}
    for name in CURRENT_FILES:
        limit = MAX_PARQUET_BYTES if name.endswith(".parquet") else MAX_FILE_BYTES
        stored[name] = read_bounded(current / name, limit)
        if hashlib.sha256(stored[name]).hexdigest() != manifest.files.get(name):
            msg = f"checksum mismatch for {name} in {where}"
            raise StoreIntegrityError(msg)
    try:
        run_manifest = RunManifest.model_validate_json(stored["run.json"])
    except ValidationError as exc:
        msg = f"cannot read run.json in {where}: {safe_error(exc)}"
        raise StoreError(msg) from exc
    if run_manifest.run_id != manifest.run_id or run_manifest.eval_fingerprint != fingerprint:
        msg = f"run.json in {where} does not belong to its manifest.json"
        raise StoreError(msg)
    expected = require_hashes(run_manifest, where)
    if hashlib.sha256(stored["results.parquet"]).hexdigest() != expected["results.parquet"]:
        msg = f"checksum mismatch for results.parquet in {where}"  # derived view: never parsed
        raise StoreIntegrityError(msg)
    plain: dict[str, bytes] = {}
    for name, original in _COMPRESSED.items():
        plain[original] = zstd_decompress(stored[name], f"{name} in {where}")
        if hashlib.sha256(plain[original]).hexdigest() != expected[original]:
            msg = f"checksum mismatch for {original} in {where}"
            raise StoreIntegrityError(msg)
    results = parse_results(run_manifest, plain["responses.jsonl"], plain["scored.jsonl"], where)
    return RunArtifacts(results=results, root=current)
