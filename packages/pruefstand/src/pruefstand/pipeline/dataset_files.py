"""Bounded, symlink-safe reading of dataset files (local and hf:// loading, T1.10/T4.7b)."""

import os
import stat
from pathlib import Path
from typing import BinaryIO

from pruefstand.core.errors import DatasetError

MAX_LINE_BYTES = 1_000_000
"""Longest accepted line of a split file."""
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1_000_000
MAX_CASES = 500_000
MANIFEST_FILE = "dataset_manifest.json"


def open_regular(path: Path) -> BinaryIO:
    """Open a regular file (no symlink, no FIFO) for binary reading."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        msg = f"{path}: cannot open (must be a regular file, not a symlink): {exc.strerror}"
        raise DatasetError(msg) from exc
    handle = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
        handle.close()
        msg = f"{path}: not a regular file"
        raise DatasetError(msg)
    return handle


def lines_of(path: Path) -> list[tuple[int, bytes]]:
    """Return ``(line number, bytes)`` of the non-blank lines, refusing over-long ones."""
    found: list[tuple[int, bytes]] = []
    total = 0
    with open_regular(path) as handle:
        number = 0
        while chunk := handle.readline(MAX_LINE_BYTES + 1):
            number += 1
            total += len(chunk)
            unterminated = len(chunk) > MAX_LINE_BYTES and not chunk.endswith(b"\n")
            if unterminated or total > MAX_FILE_BYTES:
                msg = f"{path}:{number}: line too long (limit {MAX_LINE_BYTES} bytes)"
                if total > MAX_FILE_BYTES:
                    msg = f"{path}: larger than {MAX_FILE_BYTES} bytes"
                raise DatasetError(msg)
            if chunk.strip():
                found.append((number, chunk))
            if len(found) > MAX_CASES:
                msg = f"{path}: more than {MAX_CASES} cases"
                raise DatasetError(msg)
    return found
