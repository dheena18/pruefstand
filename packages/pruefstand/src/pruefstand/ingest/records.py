"""Bounded reading of the OLDP dump files (parquet and JSON lines) for the T2.3 loaders.

The dump directories written by T2.1 (``data/raw/hf/oldp_*``) hold ``*.parquet`` files below a
config directory and a hidden ``.cache`` directory that ``snapshot_download`` leaves behind. The
files are pinned by SHA-256, but the loaders still treat them as untrusted: every limit of
:class:`OldpLimits` turns into a counted :class:`Problem`, never into an exception past the
loader, and nothing here touches the network or the Hugging Face cache.

Parquet files are streamed one row at a time (only the requested columns) after a check of the
file size and of every row group's uncompressed size in the footer; JSON lines are
read one line at a time with a hard cap on the line length, so a file without newlines cannot
exhaust memory.
"""

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import pyarrow as pa
import pyarrow.parquet as pq

from pruefstand.core.errors import PruefstandError

_MIB = 1024 * 1024
_DRAIN_CHUNK = 64 * 1024
_BATCH_ROWS = 1


class OldpDataError(PruefstandError):
    """The OLDP input directory is missing or is not a directory."""


@dataclass(frozen=True)
class Problem:
    """One counted loader problem: where (file or record), what kind, and a short detail."""

    source: str
    kind: str
    detail: str


class ProblemLog(list[Problem]):
    """A list of problems that stores only the first examples but counts every one.

    A hostile file can produce millions of bad rows; keeping one object per row would exhaust
    memory. ``counts`` (per kind) and ``total`` are exact, the list holds the first
    ``max_examples`` problems plus the first problem of every kind. Exit codes and statistics must
    use ``total`` / ``counts``, not ``len()``.

    Args:
        max_examples: How many problems to keep verbatim.

    Examples:
        >>> log = ProblemLog(max_examples=1)
        >>> for n in range(3):
        ...     log.append(Problem("f", "bad_json", str(n)))
        >>> (log.total, log.counts, len(log))
        (3, {'bad_json': 3}, 1)
    """

    def __init__(self, max_examples: int = 100) -> None:
        super().__init__()
        self.max_examples = max_examples
        self.counts: dict[str, int] = {}
        self.total = 0

    def append(self, problem: Problem) -> None:
        """Count ``problem`` and keep it when it is among the first examples or a new kind."""
        new_kind = problem.kind not in self.counts
        self.counts[problem.kind] = self.counts.get(problem.kind, 0) + 1
        self.total += 1
        if new_kind or len(self) < self.max_examples:
            super().append(problem)

    def extend(self, problems: Iterable[Problem]) -> None:
        """Append every problem of ``problems`` (counted individually)."""
        for problem in problems:
            self.append(problem)


@dataclass(frozen=True)
class OldpLimits:
    """Size limits for the OLDP loaders (the pinned 1k sample is far below all of them).

    Attributes:
        max_content_chars: Longest decision ``content`` accepted (the 1k sample's maximum is
            336 000 characters).
        max_record_bytes: Longest JSON line accepted.
        max_file_bytes: Largest data file accepted (the 1k sample's parquet is 27 MB).
        max_documents: Most decisions one load yields; the full dump is a later scale-up.
        max_rows: Most rows or lines one pass reads per file and per directory, good or bad;
            the excess is one counted ``too_many_rows`` (the 1k sample has about 1 000).
        max_group_bytes: Largest *uncompressed* parquet row group read (from the footer, before
            decoding). Parquet is streamed one row at a time; dictionary pages can decode far
            larger than the footer says, so ``max_record_bytes`` also caps the decoded row.
    """

    max_content_chars: int = 2_000_000
    max_record_bytes: int = 16 * _MIB
    max_file_bytes: int = 512 * _MIB
    max_documents: int = 10_000
    max_rows: int = 100_000
    max_group_bytes: int = 128 * _MIB


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
        yield from _parquet_rows(path, columns, limits, problems)
    else:
        yield from _jsonl_rows(path, limits, problems)


def _cap_reached(source: str, limits: OldpLimits, problems: list[Problem]) -> None:
    problems.append(Problem(source, "too_many_rows", f"more than {limits.max_rows} rows"))


def iter_dir_rows(
    files: Sequence[Path], columns: Sequence[str], limits: OldpLimits, problems: list[Problem]
) -> Iterator[tuple[str, dict[str, object]]]:
    """Yield ``(file name, row)`` over ``files``, at most ``limits.max_rows`` rows in total.

    Args:
        files: Result of :func:`data_files`.
        columns: Columns to read (see :func:`iter_rows`).
        limits: Size limits.
        problems: Where problems (including ``too_many_rows``) are recorded.

    Yields:
        The rows in file order; stops with one ``too_many_rows`` problem at the cap.
    """
    rows = 0
    for path in files:
        for row in iter_rows(path, columns, limits, problems):
            rows += 1
            if rows > limits.max_rows:
                _cap_reached(str(path.parent), limits, problems)
                return
            yield path.name, row


def valid_id(value: object) -> int | None:
    """Return ``value`` if it is a positive 63-bit integer (not a bool or float), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value < 2**63 else None


def _parquet_rows(
    path: Path, columns: Sequence[str], limits: OldpLimits, problems: list[Problem]
) -> Iterator[dict[str, object]]:
    """Stream a parquet file in batches; row groups above the uncompressed cap are skipped."""
    try:
        parquet = pq.ParquetFile(path)
        wanted = [name for name in columns if name in parquet.schema_arrow.names]
        groups: list[int] = []
        for index in range(parquet.metadata.num_row_groups):
            group = parquet.metadata.row_group(index)
            size = sum(group.column(c).total_uncompressed_size for c in range(group.num_columns))
            if size > limits.max_group_bytes:
                detail = f"{size} uncompressed bytes > {limits.max_group_bytes}"
                problems.append(Problem(f"{path.name}[{index}]", "row_group_too_large", detail))
            else:
                groups.append(index)
        examined = 0
        for batch in parquet.iter_batches(
            batch_size=_BATCH_ROWS, row_groups=groups, columns=wanted
        ):
            examined += 1
            if examined > limits.max_rows:
                _cap_reached(path.name, limits, problems)
                return
            if batch.nbytes > limits.max_record_bytes:
                detail = f"decoded row of {batch.nbytes} bytes > {limits.max_record_bytes}"
                problems.append(Problem(path.name, "record_too_large", detail))
                continue
            yield from batch.to_pylist()
    except (pa.ArrowException, OSError, ValueError) as error:
        problems.append(Problem(path.name, "bad_file", f"unreadable parquet: {error}"[:200]))


def _jsonl_rows(
    path: Path, limits: OldpLimits, problems: list[Problem]
) -> Iterator[dict[str, object]]:
    try:
        handle = path.open("rb")
    except OSError as error:
        problems.append(Problem(path.name, "bad_file", f"cannot open: {error}"))
        return
    with handle:
        number = 0
        max_record_bytes = limits.max_record_bytes
        while True:
            line = handle.readline(max_record_bytes + 1)
            if not line:
                return
            number += 1
            if number > limits.max_rows:
                _cap_reached(path.name, limits, problems)
                return
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
    except (ValueError, RecursionError) as error:  # JSONDecodeError, 4300-digit ints, nesting
        problems.append(Problem(where, "bad_json", f"{type(error).__name__}: {error}"[:200]))
        return None
    if not isinstance(parsed, dict):
        problems.append(Problem(where, "bad_json", "a JSON line must be an object"))
        return None
    return {str(key): value for key, value in parsed.items()}
