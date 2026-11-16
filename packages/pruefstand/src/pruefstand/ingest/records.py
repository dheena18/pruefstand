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

from collections.abc import Iterator, Sequence
from pathlib import Path

from pruefstand.ingest.records_model import (
    OldpDataError,
    OldpLimits,
    Problem,
    ProblemLog,
    RowBudget,
)
from pruefstand.ingest.records_proc import parquet_rows
from pruefstand.ingest.records_read import jsonl_rows

__all__ = [
    "OldpDataError",
    "OldpLimits",
    "Problem",
    "ProblemLog",
    "RowBudget",
    "data_files",
    "iter_dir_rows",
    "iter_rows",
    "valid_id",
]


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
    for _, row in _located_rows(path, columns, limits, problems, RowBudget(limits.max_rows)):
        yield row


def _located_rows(
    path: Path,
    columns: Sequence[str],
    limits: OldpLimits,
    problems: list[Problem],
    budget: RowBudget,
) -> Iterator[tuple[int, dict[str, object]]]:
    """Like :func:`iter_rows`, with the 1-based line (JSON lines) or row (parquet) number."""
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
        yield from parquet_rows(path, columns, limits, problems, budget)
    else:
        yield from jsonl_rows(path, limits, problems, budget)


def iter_dir_rows(
    files: Sequence[Path], columns: Sequence[str], limits: OldpLimits, problems: list[Problem]
) -> Iterator[tuple[str, dict[str, object]]]:
    """Yield ``(where, row)`` over ``files`` within one shared budget of ``limits.max_rows``.

    Every row or line examined, good or bad, is charged to the budget, and at most
    ``limits.max_files`` files are opened (T2.3a).

    Args:
        files: Result of :func:`data_files`.
        columns: Columns to read (see :func:`iter_rows`).
        limits: Size limits.
        problems: Where problems (including ``too_many_rows`` / ``too_many_files``) are recorded.

    Yields:
        ``("<file name>:<line or row number>", row)`` in file order; stops with one
        ``too_many_rows`` problem when the budget is used up.
    """
    budget = RowBudget(limits.max_rows)
    if len(files) > limits.max_files:
        detail = f"{len(files)} files, only the first {limits.max_files} are read"
        problems.append(Problem(str(files[0].parent), "too_many_files", detail))
    for path in files[: limits.max_files]:
        for number, row in _located_rows(path, columns, limits, problems, budget):
            yield f"{path.name}:{number}", row
        if budget.hit:
            return


def valid_id(value: object) -> int | None:
    """Return ``value`` if it is a positive 63-bit integer (not a bool or float), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value < 2**63 else None
