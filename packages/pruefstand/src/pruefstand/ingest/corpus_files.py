"""Shared rules for the files of ``corpus/<corpus_version>/`` (T2.5): names, limits, reading."""

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from pruefstand.core.config.build import validate_tenant_id
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import TenantId

MANIFEST_NAME = "manifest.json"
FILE_SUFFIX = ".chunks.jsonl"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024  # one chunk; loaders cap their texts far below this
BANNED_SOURCES = ("memerag",)  # CC BY-NC: download-only, never part of a corpus (CLAUDE.md §9)
_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9a-f]{8}")


def tenant_file(tenant: str) -> str:
    """Return ``"<tenant>.chunks.jsonl"``."""
    return f"{tenant}{FILE_SUFFIX}"


def checked_tenant(tenant: str, where: str) -> TenantId:
    """Return ``tenant`` if it is a safe tenant id.

    Args:
        tenant: The id found on a chunk or in a manifest.
        where: What carries it, for the message (``"chunk x"``).

    Raises:
        DatasetError: The id is not safe to use as a file name.
    """
    try:
        return validate_tenant_id(tenant)
    except ValueError as exc:
        msg = f"{where}: {exc}"
        raise DatasetError(msg) from exc


def checked_version(version: str) -> date:
    """Return the date part of a ``corpus_version``.

    Args:
        version: ``"<YYYY-MM-DD>.<8 hex>"``.

    Raises:
        DatasetError: The string has another shape (so it cannot be a path component either).
    """
    if not _VERSION.fullmatch(version):
        msg = f"corpus_version {version[:40]!r} must look like 2026-11-02.ab12cd34"
        raise DatasetError(msg)
    try:
        return date.fromisoformat(version[:10])
    except ValueError as exc:
        msg = f"corpus_version {version!r} does not start with a valid date"
        raise DatasetError(msg) from exc


def created_at(version: str) -> datetime:
    """Midnight UTC of the version's date (no clock needed, so the output is reproducible)."""
    day = checked_version(version)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def open_regular(path: Path) -> int:
    """Open ``path`` read-only without following a symlink and return the descriptor.

    Raises:
        DatasetError: The path is a symlink, not a regular file, or cannot be opened.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        msg = f"{path.name}: cannot open (a symlink or an unreadable file): {exc.strerror}"
        raise DatasetError(msg) from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        msg = f"{path.name}: not a regular file"
        raise DatasetError(msg)
    return fd


def read_regular(path: Path, limit: int) -> bytes:
    """Read a whole regular file of at most ``limit`` bytes.

    Raises:
        DatasetError: Symlink, not a regular file, or larger than ``limit``.
    """
    with os.fdopen(open_regular(path), "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        msg = f"{path.name}: larger than {limit} bytes"
        raise DatasetError(msg)
    return data


def iter_lines(path: Path) -> Iterator[bytes]:
    r"""Yield the lines of a regular file (with their ``\n``), none longer than ``MAX_LINE_BYTES``.

    Raises:
        DatasetError: Symlink, not a regular file, or a line over the limit.
    """
    with os.fdopen(open_regular(path), "rb") as handle:
        while line := handle.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                msg = f"{path.name}: a line is longer than {MAX_LINE_BYTES} bytes"
                raise DatasetError(msg)
            yield line


def file_sha256(path: Path) -> str:
    """Return the SHA-256 (hex) of a regular file, read in blocks.

    Raises:
        DatasetError: Symlink or not a regular file.
    """
    digest = hashlib.sha256()
    with os.fdopen(open_regular(path), "rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()
