"""Bounded reading of the OLDP dump files (parquet and JSON lines) for the T2.3 loaders.

The dump directories written by T2.1 (``data/raw/hf/oldp_*``) hold ``*.parquet`` files below a
config directory and a hidden ``.cache`` directory that ``snapshot_download`` leaves behind. The
files are pinned by SHA-256, but the loaders still treat them as untrusted: every limit of
:class:`OldpLimits` turns into a counted :class:`Problem`, never into an exception past the
loader, and nothing here touches the network or the Hugging Face cache.

Parquet files are read whole (only the requested columns) after a file-size check; JSON lines are
read one line at a time with a hard cap on the line length, so a file without newlines cannot
exhaust memory.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import polars as pl

from pruefstand.core.errors import PruefstandError

_MIB = 1024 * 1024
_DRAIN_CHUNK = 64 * 1024


class OldpDataError(PruefstandError):
    """The OLDP input directory is missing or is not a directory."""


@dataclass(frozen=True)
class Problem:
    """One counted loader problem: where (file or record), what kind, and a short detail."""

    source: str
    kind: str
    detail: str


@dataclass(frozen=True)
class OldpLimits:
    """Size limits for the OLDP loaders (the pinned 1k sample is far below all of them).

    Attributes:
        max_content_chars: Longest decision ``content`` accepted (the 1k sample's maximum is
            336 000 characters).
        max_record_bytes: Longest JSON line accepted.
        max_file_bytes: Largest data file accepted (the 1k sample's parquet is 27 MB).
        max_documents: Most decisions one load yields; the full dump is a later scale-up.
        max_rows: Most rows one pass over a directory reads (citation graph edges).
    """

    max_content_chars: int = 2_000_000
    max_record_bytes: int = 16 * _MIB
    max_file_bytes: int = 512 * _MIB
    max_documents: int = 10_000
    max_rows: int = 2_000_000


def data_files(directory: Path) -> list[Path]:
    """Return the ``*.parquet`` and ``*.jsonl`` files below ``directory`` in sorted order.

    Files inside hidden directories (``.cache``) are ignored.

    Args:
        directory: A dump directory such as ``data/raw/hf/oldp_decisions``.

    Returns:
        The sorted file paths; empty when there are none.

    Raises:
        OldpDataError: ``directory`` is not a directory.
    """
    if not directory.is_dir():
        msg = f"not a directory: {directory}"
        raise OldpDataError(msg)
    found = [
        path
        for pattern in ("*.parquet", "*.jsonl")
        for path in directory.rglob(pattern)
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    ]
    return sorted(found)


def iter_rows(
    path: Path, columns: Sequence[str], limits: OldpLimits, problems: list[Problem]
) -> Iterator[dict[str, object]]:
    """Yield the rows of one data file as dicts, recording problems instead of raising.

    Args:
        path: A ``.parquet`` or ``.jsonl`` file.
        columns: The columns the caller needs; parquet reads only these (missing ones are absent
            from the rows), JSON lines keep every key.
        limits: Size limits.
        problems: List the problems are appended to.

    Yields:
        One dict per readable row, in file order.
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        problems.append(Problem(path.name, "bad_file", f"cannot stat: {error}"))
        return
    if size > limits.max_file_bytes:
        detail = f"{size} bytes > {limits.max_file_bytes}"
        problems.append(Problem(path.name, "file_too_large", detail))
        return
    if path.suffix == ".parquet":
        yield from _parquet_rows(path, columns, problems)
    else:
        yield from _jsonl_rows(path, limits.max_record_bytes, problems)


def _parquet_rows(
    path: Path, columns: Sequence[str], problems: list[Problem]
) -> Iterator[dict[str, object]]:
    try:
        available = pl.read_parquet_schema(path)
        wanted = [name for name in columns if name in available]
        frame = pl.read_parquet(path, columns=wanted)
    except (pl.exceptions.PolarsError, OSError, ValueError) as error:
        problems.append(Problem(path.name, "bad_file", f"unreadable parquet: {error}"[:200]))
        return
    yield from frame.iter_rows(named=True)


def _jsonl_rows(
    path: Path, max_record_bytes: int, problems: list[Problem]
) -> Iterator[dict[str, object]]:
    try:
        handle = path.open("rb")
    except OSError as error:
        problems.append(Problem(path.name, "bad_file", f"cannot open: {error}"))
        return
    with handle:
        number = 0
        while True:
            line = handle.readline(max_record_bytes + 1)
            if not line:
                return
            number += 1
            where = f"{path.name}:{number}"
            if len(line) > max_record_bytes and not line.endswith(b"\n"):
                _drain(handle)
                problems.append(Problem(where, "record_too_large", f"> {max_record_bytes} bytes"))
                continue
            if not line.strip():
                continue
            row = _parse_line(line, where, problems)
            if row is not None:
                yield row


def _drain(handle: IO[bytes]) -> None:
    """Skip the rest of an over-long line without holding it in memory."""
    while True:
        rest = handle.readline(_DRAIN_CHUNK)
        if not rest or rest.endswith(b"\n"):
            return


def _parse_line(line: bytes, where: str, problems: list[Problem]) -> dict[str, object] | None:
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        problems.append(Problem(where, "bad_json", f"{type(error).__name__}: {error}"[:200]))
        return None
    if not isinstance(parsed, dict):
        problems.append(Problem(where, "bad_json", "a JSON line must be an object"))
        return None
    return {str(key): value for key, value in parsed.items()}
