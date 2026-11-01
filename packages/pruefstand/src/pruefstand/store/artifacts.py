"""``ArtifactStore``: writes and reads run directories losslessly (interfaces §7, §1.4).

A run directory holds ``run.json`` (the manifest), ``results.parquet`` (the 13-column analytics
view), ``responses.jsonl`` (``CaseRecord`` per case), ``scored.jsonl`` (``ScoredCase`` per case;
the lossless source of ``RunResults.values``, because the parquet view has no ``TestCase`` body
or metric details) and optionally ``llm_calls.parquet``. Writes go to a temporary sibling
directory that is renamed into place, so a failed write leaves nothing behind (D358).
"""

import fcntl
import json
import os
import re
import secrets
import shutil
import stat
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from pruefstand.core.errors import StoreError
from pruefstand.core.ids import RunId
from pruefstand.core.models.run import RunArtifacts, RunManifest
from pruefstand.store._run_files import (
    MAX_FILE_BYTES,
    MAX_MANIFEST_BYTES,
    RESULT_COLUMNS,
    manifest_text,
    read_bounded,
    read_results,
    safe_error,
    write_files,
)

COUNT_KEYS = frozenset({"model_reloads", "upstream_errors"})
"""The only counters ``add_counts`` accepts (written by the executor, R12 N6.4)."""

__all__ = ["COUNT_KEYS", "RESULT_COLUMNS", "ArtifactStore", "new_run_id"]


def new_run_id(now: datetime | None = None) -> RunId:
    """Return ``<UTC yyyymmddTHHMMSS>-<6 hex>``.

    Args:
        now: Timestamp to use (UTC); default is the current time.

    Examples:
        >>> from datetime import datetime, UTC
        >>> new_run_id(datetime(2026, 11, 2, 22, 5, 9, tzinfo=UTC))[:16]
        '20261102T220509-'
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    return RunId(f"{stamp:%Y%m%dT%H%M%S}-{secrets.token_hex(3)}")


class ArtifactStore:
    """Run directories under one root.

    Args:
        root: Directory that holds ``<run_id>/`` subdirectories.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def write_run(self, run: RunArtifacts, *, llm_calls: pl.DataFrame | None = None) -> Path:
        """Write ``run`` into ``run.root`` atomically and return that directory.

        Args:
            run: The run; ``run.root`` must lie under the store root and not exist yet.
            llm_calls: Optional call log, written as ``llm_calls.parquet``.

        Returns:
            ``run.root``.

        Raises:
            StoreError: ``run.root`` is outside the store root, exists already, or a write
                failed (nothing is left behind then).
        """
        target = run.root
        root = self._root.resolve()
        resolved = target.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            msg = f"run root {target} must be a directory under the store root {self._root}"
            raise StoreError(msg)
        if target.exists():
            msg = f"run directory {target} exists; a stored run is never overwritten"
            raise StoreError(msg)
        tmp = target.parent / f".{target.name}.{secrets.token_hex(4)}.tmp"
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            _remove_stale_tmp_dirs(tmp.parent)
            tmp.mkdir()
            write_files(tmp, run.results, llm_calls)
            Path(tmp).replace(target)
        except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
            # ValueError covers pydantic serialisation errors and UnicodeError (lone surrogates)
            shutil.rmtree(tmp, ignore_errors=True)
            detail = (
                str(exc)
                if isinstance(exc, OSError | pl.exceptions.PolarsError)
                else safe_error(exc)
            )
            msg = f"cannot write run {target.name}: {detail}"
            raise StoreError(msg) from exc
        return target

    def read_run(self, run_id_or_path: str | Path) -> RunArtifacts:
        """Read a run directory.

        Args:
            run_id_or_path: A run id (looked up under the store root) or a directory path.

        Returns:
            ``RunArtifacts`` whose ``results`` equal what was written and whose ``root`` is the
            directory.

        Raises:
            StoreError: The run is missing, a file is invalid, or the files disagree.
        """
        path = self._locate(run_id_or_path)
        return RunArtifacts(results=read_results(path), root=path)

    def mark_aborted(self, run_id_or_path: str | Path, infra_error: str) -> None:
        """Rewrite ``run.json`` as aborted by an infrastructure failure (R11 D245).

        Sets ``complete=False``, ``stop_reason="aborted"`` and ``infra_error``; every other
        file stays untouched. Called only by the executor (T6.2a).

        Args:
            run_id_or_path: The run.
            infra_error: ``"<kind>: <detail>"``.

        Raises:
            StoreError: The run is missing or the new manifest is invalid.
        """
        self._update(
            run_id_or_path,
            lambda data: {
                **data, "complete": False, "stop_reason": "aborted", "infra_error": infra_error
            },
        )  # fmt: skip

    def add_counts(self, run_id_or_path: str | Path, counts: Mapping[str, int]) -> None:
        """Merge ``model_reloads`` / ``upstream_errors`` into ``run.json`` (R12 N6.4, D267).

        Existing counts are kept; other files stay untouched. Called only by the executor
        (T6.2a) with the ``llm-proxy`` ``/health`` differences.

        Args:
            run_id_or_path: The run.
            counts: Counter name -> value; only ``model_reloads`` and ``upstream_errors``.

        Raises:
            StoreError: A key is not accepted (nothing is written), or the run is missing.
        """
        unknown = sorted(set(counts) - COUNT_KEYS)
        if unknown:
            msg = f"add_counts accepts only {sorted(COUNT_KEYS)}, not {unknown}"
            raise StoreError(msg)
        self._update(run_id_or_path, lambda data: {**data, "counts": {**data["counts"], **counts}})

    def _update(
        self, run_id_or_path: str | Path, change: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        path = self._locate(run_id_or_path)
        fd = os.open(path, os.O_RDONLY)  # an exclusive lock on the directory serialises updaters
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._update_locked(path, change)
        finally:
            os.close(fd)

    @staticmethod
    def _update_locked(path: Path, change: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        # ONE bounded read of run.json, validated before and after the change
        raw = read_bounded(path / "run.json", min(MAX_MANIFEST_BYTES, MAX_FILE_BYTES))
        try:
            data = json.loads(raw)
            RunManifest.model_validate(data)
            manifest = RunManifest.model_validate(change(data))
        except (ValueError, KeyError, TypeError) as exc:
            msg = f"invalid manifest for {path.name}: {safe_error(exc)}"
            raise StoreError(msg) from exc
        tmp = path / f"run.json.{secrets.token_hex(4)}.tmp"
        try:
            tmp.write_text(manifest_text(manifest), encoding="utf-8")
            Path(tmp).replace(path / "run.json")
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            msg = f"cannot update run.json of {path.name}: {exc}"
            raise StoreError(msg) from exc

    def _locate(self, run_id_or_path: str | Path) -> Path:
        text = str(run_id_or_path)
        is_id = os.sep not in text and "/" not in text and text not in {"", ".", ".."}
        path = self._root / text if is_id else Path(run_id_or_path)
        try:
            info = os.lstat(path)
        except OSError as exc:
            msg = f"no run directory at {path}"
            raise StoreError(msg) from exc
        if stat.S_ISLNK(info.st_mode):
            msg = f"run directory {path} is a symlink; refusing to follow it"
            raise StoreError(msg)
        if not stat.S_ISDIR(info.st_mode) or not path.resolve().is_relative_to(
            self._root.resolve()
        ):
            msg = f"{path} is not a run directory under the store root"
            raise StoreError(msg)
        return path


_STALE_NAME = re.compile(r"^\.[A-Za-z0-9_-]+\.[0-9a-f]{8}\.tmp$")


def _newest_mtime(directory: Path) -> float:
    newest = directory.lstat().st_mtime
    for entry in directory.rglob("*"):
        newest = max(newest, entry.lstat().st_mtime)
    return newest


def _remove_stale_tmp_dirs(parent: Path, max_age_s: float = 86400.0) -> None:
    """Delete ``.<run>.<8 hex>.tmp`` directories whose newest file is older than a day."""
    cutoff = time.time() - max_age_s
    for entry in parent.iterdir():
        try:
            stale_name = _STALE_NAME.match(entry.name) and not entry.is_symlink()
            if stale_name and entry.is_dir() and _newest_mtime(entry) < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue
