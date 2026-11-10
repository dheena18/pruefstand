"""Reader process for parquet files under hard limits (T2.3a; review F5, D1122): ``records_child``.

Started by :func:`pruefstand.ingest.records_proc.parquet_rows`; reads the arguments from argv
(JSON), limits the address space to what it uses after the imports plus ``memory`` bytes (soft =
hard, so it cannot be raised again) and the CPU time, and streams events to stdout as JSON lines
(:mod:`~pruefstand.ingest.records_wire`, no pickle): ``("row", number, row)``, ``("problem",
source, kind, detail)``, ``("warning", text)``, ``("memory", message)`` and finally ``("done",
rows_left, hit)``. Every row is checked here before it is sent: only ``str``/``int``/``float``/
``bool``/``None``, dates, times, ``Decimal`` and dicts/lists of them, strings up to
``max_record_bytes`` characters, at most ``max_list_elements`` list items per row; anything else
is one ``bad_record``. Only this process ever touches the untrusted file's decoded data.
"""

import json
import resource
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

import pyarrow as pa

from pruefstand.core.errors import PruefstandError
from pruefstand.ingest.records_model import OldpLimits, Problem, RowBudget
from pruefstand.ingest.records_read import parquet_rows_local
from pruefstand.ingest.records_wire import WireError, encode

_MAX_DEPTH = 8
_SCALARS = (str, int, float, bool, type(None), Decimal, date, time, timedelta)


def _virtual_bytes() -> int:
    """Current virtual size of this process (Linux ``/proc``); 0 when unavailable."""
    try:
        pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return 0
    return pages * resource.getpagesize()


def _limit_memory(extra: int) -> str | None:
    """Limit the address space to its current size plus ``extra``; return a warning if it fails.

    Soft and hard limit are set to the same value (a compromised reader cannot raise its soft
    limit again); it is clamped to an existing finite hard limit (``ulimit -v``). Without
    ``/proc`` or when the limit cannot be set, the reader runs unlimited and says so.
    """
    if extra <= 0:
        return None
    base = _virtual_bytes()
    if base <= 0:
        return "memory limit not set: /proc/self/statm is unavailable"
    hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    soft = base + extra if hard == resource.RLIM_INFINITY else min(base + extra, hard)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
    except (ValueError, OSError) as error:
        return f"memory limit not set: {error}"
    return None


def limit_resources(limits: OldpLimits) -> str | None:
    """Set the memory limit and the CPU-time limit (soft = hard); return a warning if one fails."""
    warning = _limit_memory(limits.max_parquet_memory_bytes)
    seconds = limits.max_parquet_cpu_seconds
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    except (ValueError, OSError) as error:
        return warning or f"CPU limit not set: {error}"
    return warning


def send(out: BinaryIO, event: tuple[object, ...]) -> None:
    """Write one event as a JSON line (:mod:`~pruefstand.ingest.records_wire`, never pickle)."""
    out.write(encode(event))
    out.flush()


class RowRejectedError(PruefstandError):
    """A row value the parent must never receive."""


def _clean(value: object, limits: OldpLimits, depth: int, items: list[int]) -> object:
    if depth > _MAX_DEPTH:
        msg = "nested deeper than 8 levels"
        raise RowRejectedError(msg)
    if isinstance(value, str) and len(value) > limits.max_record_bytes:
        msg = f"a text of {len(value)} characters"
        raise RowRejectedError(msg)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=timezone(value.utcoffset() or timedelta(0)))
    if isinstance(value, time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if isinstance(value, _SCALARS):
        return value
    if isinstance(value, list | tuple):
        items[0] += len(value)
        if items[0] > limits.max_list_elements:
            msg = f"more than {limits.max_list_elements} list elements"
            raise RowRejectedError(msg)
        return [_clean(v, limits, depth + 1, items) for v in value]
    if isinstance(value, dict):
        return {str(k): _clean(v, limits, depth + 1, items) for k, v in value.items()}
    msg = f"unsupported value type {type(value).__name__}"
    raise RowRejectedError(msg)


def clean_row(row: dict[str, object], limits: OldpLimits) -> dict[str, object]:
    """The row as the parent may receive it.

    Raises:
        RowRejectedError: A value of another type, too long, too deep or too many list elements.
    """
    items = [0]
    return {str(k): _clean(v, limits, 1, items) for k, v in row.items()}


def _row_line(
    number: int, row: dict[str, object], limits: OldpLimits, problems: list[Problem], path: Path
) -> bytes | None:
    """The row's JSON line, or None after one ``bad_record`` problem."""
    try:
        return encode(("row", number, clean_row(row, limits)))
    except (RowRejectedError, WireError) as error:
        problems.append(Problem(f"{path.name}:{number}", "bad_record", str(error)))
        return None


def run(argv: list[str], out: BinaryIO) -> int:
    """Read the file named in ``argv[0]`` (JSON ``{path, columns, limits, left}``)."""
    spec = json.loads(argv[0])
    limits = OldpLimits(**spec["limits"])
    budget = RowBudget(spec["left"])
    problems: list[Problem] = []
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    warning = limit_resources(limits)
    if warning is not None:
        send(out, ("warning", warning))
    path = Path(spec["path"])
    try:
        for number, row in parquet_rows_local(path, spec["columns"], limits, problems, budget):
            line = _row_line(number, row, limits, problems, path)
            while problems:
                problem = problems.pop(0)
                send(out, ("problem", problem.source, problem.kind, problem.detail))
            if line is not None:
                out.write(line)
                out.flush()
        while problems:
            problem = problems.pop(0)
            send(out, ("problem", problem.source, problem.kind, problem.detail))
    except MemoryError as error:
        send(out, ("memory", f"{type(error).__name__}: {error}"[:200]))
        return 0
    send(out, ("done", budget.left, budget.hit))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdout.buffer))
