"""Validation of an export directory before it is published (T6.1 S9, D448).

The source is checked without any network access and without trusting it: the sanitised marker,
the exact file list and SHA-256 values of ``manifest.json``, no symlink, size limits, and no
``CANARY-`` in any file. The ``extra`` files of a push are checked for path safety here too.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pruefstand.core.errors import StoreError
from pruefstand.store._dashboard_tree import MAX_JSON_BYTES
from pruefstand.store._run_files import read_bounded
from pruefstand.store.baseline_index import validate_run_id

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SRC_BYTES = 256 * 1024 * 1024
MAX_SRC_FILES = 5000
MAX_EXTRA_BYTES = 8 * 1024 * 1024
_CANARY = re.compile(rb"canary-", re.IGNORECASE)
_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class Export:
    """A validated source directory."""

    root: Path
    run_id: str
    files: tuple[str, ...]
    data: dict[str, bytes]
    """The verified bytes of every file: what is written is what was hashed and scanned."""


def _collect(src: Path) -> dict[str, Path]:
    """The regular files below ``src`` by relative path; a symlink or a size excess is an error."""
    if src.is_symlink() or not src.is_dir():
        msg = f"{src} is not a directory"
        raise StoreError(msg)
    found: dict[str, Path] = {}
    total = 0
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            msg = f"{path.relative_to(src)} is a symlink; exports hold regular files only"
            raise StoreError(msg)
        if path.is_file():
            if path.lstat().st_nlink > 1:
                msg = f"{path.relative_to(src)} is a hard link; exports hold plain files only"
                raise StoreError(msg)
            total += path.lstat().st_size
            found[path.relative_to(src).as_posix()] = path
    if len(found) > MAX_SRC_FILES or total > MAX_SRC_BYTES:
        msg = f"the export holds {len(found)} files / {total} bytes: over the size limits"
        raise StoreError(msg)
    return found


def _marker(src: Path) -> dict[str, object]:
    try:
        marker = json.loads(read_bounded(src / "manifest.json", MAX_JSON_BYTES))
    except (StoreError, ValueError) as exc:
        msg = f"{src} was not produced by sanitise_run (no readable manifest.json marker)"
        raise StoreError(msg) from exc
    if not isinstance(marker, dict) or marker.get("sanitised") is not True:
        msg = f"{src} was not produced by sanitise_run (manifest.json has no sanitised marker)"
        raise StoreError(msg)
    return marker


def load_export(src: Path) -> Export:
    """Check a source directory without trusting it: marker, hashes, links, sizes, canaries."""
    found = _collect(src)
    marker = _marker(src)
    listed = marker.get("files")
    names = sorted(n for n in found if n != "manifest.json")
    if not isinstance(listed, dict) or sorted(listed) != names:
        msg = "manifest.json does not list exactly the files of the export"
        raise StoreError(msg)
    verified: dict[str, bytes] = {}
    for name in names:
        data = read_bounded(found[name], MAX_FILE_BYTES)
        verified[name] = data
        if hashlib.sha256(data).hexdigest() != listed[name]:
            msg = f"manifest.json does not match {name}: the export changed after it was sealed"
            raise StoreError(msg)
        if _CANARY.search(data):
            msg = f"refusing to publish: {name} contains 'CANARY-'"
            raise StoreError(msg)
    run_id = marker.get("run_id")
    if not isinstance(run_id, str):
        msg = "manifest.json names no run_id"
        raise StoreError(msg)
    return Export(src, validate_run_id(run_id), tuple(names), verified)


def check_extra(extra: Mapping[str, bytes] | None) -> dict[str, bytes]:
    checked: dict[str, bytes] = {}
    total = 0
    for name, data in (extra or {}).items():
        parts = name.split("/")
        bad = (
            not name
            or name.startswith("/")
            or any(_PART.fullmatch(p) is None or p.startswith(".git") for p in parts)
            or parts[0] in {"runs", "cases"}
            or name == "manifest.json"
        )
        if bad:
            msg = (
                f"extra file {name[:60]!r} is not allowed (relative path, not under runs/, cases/)"
            )
            raise StoreError(msg)
        if _CANARY.search(data):
            msg = f"extra file {name!r} contains 'CANARY-': refusing to publish"
            raise StoreError(msg)
        total += len(data)
        checked[name] = data
    if total > MAX_EXTRA_BYTES:
        msg = "the extra files are larger than the limit"
        raise StoreError(msg)
    return checked
