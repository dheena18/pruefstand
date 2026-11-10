"""Atomic promotion of a run into the data root (write-then-rename, gpu-cluster.md §9).

A baseline directory is staged as ``<name>.<hex>.partial`` (every file fsynced), the old current
directory is renamed to ``<ref>.<hex>.old``, the staged one takes its place and ``history/<run_id>``
is renamed in. The returned ``Promotion`` stays open until the caller has published the index:
``commit`` forgets the old baseline, ``rollback`` restores it. Readers ignore ``*.partial`` and
``*.old``.
"""

import hashlib
import os
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import zstandard

from pruefstand.core.errors import StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.baseline import PromotionOverride
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store._baseline_dir import (
    HISTORY_FILES,
    MANIFEST,
    BaselineManifest,
    leftovers,
    manifest_bytes,
    real_dir,
    remove_tree,
    zstd_compress,
)
from pruefstand.store._run_render import render_files
from pruefstand.store._safe_error import safe_error
from pruefstand.store.baseline_index import (
    IndexEntry,
    validate_fingerprint,
    validate_ref,
    validate_run_id,
)
from pruefstand.store.promote import check_promotable, check_ref_block

_log = get_logger(__name__)
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """The default clock of the stores."""
    return datetime.now(UTC)


@dataclass
class Promotion:
    """A baseline already renamed into place whose publication is still open.

    ``commit`` removes the previous baseline; ``rollback`` restores it and removes the new files.
    """

    fingerprint: str
    ref: str
    entry: IndexEntry
    current: Path
    previous: Path | None
    history: Path | None

    def commit(self) -> None:
        """Forget the previous baseline (a failed delete only leaves a harmless ``.old``)."""
        if self.previous is not None:
            try:
                remove_tree(self.previous)
            except StoreError as exc:
                _log.warning("baseline_old_not_deleted", error=str(exc))

    def rollback(self) -> None:
        """Put the previous baseline back and delete the new files."""
        remove_tree(self.current)
        if self.previous is not None:
            self.previous.rename(self.current)
        if self.history is not None:
            remove_tree(self.history)


def safe_rollback(promotion: Promotion) -> None:
    """Roll a promotion back; a failure of the rollback itself is logged, not raised.

    The caller is already handling the error that made the rollback necessary.
    """
    try:
        promotion.rollback()
    except (StoreError, OSError) as exc:
        _log.error("baseline_rollback_failed", fingerprint=promotion.fingerprint, error=str(exc))


def promote_to_disk(
    root: Path,
    run: RunArtifacts,
    ref: str,
    clock: Clock,
    *,
    override: PromotionOverride | None = None,
) -> Promotion:
    """Write ``run`` as the current baseline of ``(its fingerprint, ref)`` and into ``history/``.

    Args:
        root: The data root (must exist).
        run: The run to store; refused when incomplete or flagged.
        ref: One of the refs; the run's block must fit it.
        clock: Source of ``promoted_at``.
        override: The owner's recorded ``--allow-failed-gate`` (manifest and index, D1123).

    Returns:
        The open promotion; the caller publishes it, then ``commit`` or ``rollback``.

    Raises:
        BaselineRefused: Incomplete or flagged run.
        StoreError: Unsafe names, a block that does not fit the ref, a symlink on the path, or a
            write failure (the previous baseline is intact then).
    """
    manifest = run.results.manifest
    validate_ref(ref)
    validate_fingerprint(manifest.eval_fingerprint)
    validate_run_id(manifest.run_id)
    check_promotable(manifest)
    check_ref_block(manifest, ref)
    try:
        return _write(root, run, ref, clock(), override)
    except (OSError, ValueError, zstandard.ZstdError) as exc:
        detail = str(exc) if isinstance(exc, OSError) else safe_error(exc)
        msg = f"cannot write the baseline {manifest.eval_fingerprint}/{ref}: {detail}"
        raise StoreError(msg) from exc


@dataclass(frozen=True)
class _Serialised:
    """Everything that will be written, as bytes."""

    stored: dict[str, bytes]
    current_manifest: bytes
    history_manifest: bytes
    entry: IndexEntry


def _serialise(
    run: RunArtifacts, ref: str, promoted_at: datetime, override: PromotionOverride | None
) -> _Serialised:
    manifest = run.results.manifest
    plain = render_files(run.results)
    stored = {
        "run.json": plain["run.json"],
        "results.parquet": plain["results.parquet"],
        "responses.jsonl.zst": zstd_compress(plain["responses.jsonl"]),
        "scored.jsonl.zst": zstd_compress(plain["scored.jsonl"]),
    }
    shas = {name: hashlib.sha256(data).hexdigest() for name, data in stored.items()}
    current = BaselineManifest(
        schema_version="1",
        run_id=manifest.run_id,
        eval_fingerprint=manifest.eval_fingerprint,
        ref=ref,
        promoted_at=promoted_at,
        git_sha=manifest.git_sha,
        files=shas,
        override=override,
    )
    history = current.model_copy(update={"files": {n: shas[n] for n in HISTORY_FILES}})
    current_bytes = manifest_bytes(current)
    entry = IndexEntry(
        run_id=manifest.run_id,
        manifest_sha256=hashlib.sha256(current_bytes).hexdigest(),
        promoted_at=promoted_at,
        git_sha=manifest.git_sha,
        override=override,
    )
    return _Serialised(stored, current_bytes, manifest_bytes(history), entry)


def _ensure_dir(path: Path) -> Path:
    if not real_dir(path, missing_ok=True):
        path.mkdir()
    return path


def _write(
    root: Path,
    run: RunArtifacts,
    ref: str,
    promoted_at: datetime,
    override: PromotionOverride | None,
) -> Promotion:
    manifest = run.results.manifest
    real_dir(root)
    base = _ensure_dir(root / manifest.eval_fingerprint)
    _clean_leftovers(base, ref)
    data = _serialise(run, ref, promoted_at, override)
    token = secrets.token_hex(4)
    history_dir = _ensure_dir(base / "history")
    final_history = history_dir / manifest.run_id
    staged: list[Path] = []
    history: Path | None = None
    try:
        files = {**data.stored, MANIFEST: data.current_manifest}
        partial = _stage(base, f"{ref}.{token}.partial", files)
        staged.append(partial)
        if not real_dir(final_history, missing_ok=True):
            kept = {n: data.stored[n] for n in HISTORY_FILES} | {MANIFEST: data.history_manifest}
            history = _stage(history_dir, f"{manifest.run_id}.{token}.partial", kept)
            staged.append(history)
        current, previous = _swap(base, ref, partial, token)
    except BaseException:
        for leftover in staged:
            shutil.rmtree(leftover, ignore_errors=True)
        raise
    promotion = Promotion(manifest.eval_fingerprint, ref, data.entry, current, previous, None)
    if history is not None:
        _publish_history(promotion, history, final_history)
    _fsync_dir(base)
    return promotion


def _publish_history(promotion: Promotion, staged: Path, final: Path) -> None:
    try:
        staged.rename(final)
    except OSError:
        promotion.rollback()
        shutil.rmtree(staged, ignore_errors=True)
        raise
    promotion.history = final


def _swap(base: Path, ref: str, partial: Path, token: str) -> tuple[Path, Path | None]:
    """Rename ``partial`` over the current baseline, keeping the old one as ``<ref>.<hex>.old``."""
    current = base / ref
    previous: Path | None = None
    if real_dir(current, missing_ok=True):
        previous = base / f"{ref}.{token}.old"
        current.rename(previous)
    try:
        partial.rename(current)
    except OSError:
        if previous is not None:
            previous.rename(current)
        raise
    return current, previous


def _stage(parent: Path, name: str, files: dict[str, bytes]) -> Path:
    """Write ``files`` into a new directory ``parent/name`` and fsync it."""
    target = parent / name
    target.mkdir()
    try:
        for filename, data in files.items():
            fd = os.open(target / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        _fsync_dir(target)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _clean_leftovers(base: Path, ref: str) -> None:
    """Remove ``.partial`` leftovers of ``ref``, and ``.old`` ones once the ref is in place."""
    in_place = real_dir(base / ref, missing_ok=True)
    for match in list(leftovers(base)):
        if match.group("name") != ref:
            continue
        if match.group("kind") == "partial" or in_place:
            remove_tree(base / match.group(0))
