"""Bounded reads of files whose path comes from the environment (counter file, event file)."""

import os
import stat
from pathlib import Path


class NotRegularFileError(OSError):
    """The path is not a regular file (a FIFO, a device or a directory)."""


def read_regular(path: Path, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes of a regular file without ever blocking.

    The file is opened non-blocking (a FIFO would otherwise hang the run) and must be a regular
    file after ``fstat``; callers compare the length with ``limit`` to detect an oversized file.

    Args:
        path: The file.
        limit: The largest accepted size in bytes.

    Returns:
        Up to ``limit + 1`` bytes.

    Raises:
        NotRegularFileError: The path is not a regular file.
        OSError: The file cannot be opened or read.
    """
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            msg = f"{path}: not a regular file"
            raise NotRegularFileError(msg)
        return handle.read(limit + 1)
