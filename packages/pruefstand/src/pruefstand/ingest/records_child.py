"""Reader process for parquet files under a hard memory limit (T2.3a): ``records_child``.

Started by :func:`pruefstand.ingest.records_read.parquet_rows`; reads the arguments from argv
(JSON), limits the address space to what it uses after the imports plus ``memory`` bytes, and
streams pickled events to stdout: ``("row", number, row)``, ``("problem", Problem)``,
``("memory", message)`` and finally ``("done", rows_left, hit)``. Only this process ever touches
the untrusted file's decoded data; the parent reads events produced by this module.
"""

import json
import pickle
import resource
import sys
from pathlib import Path
from typing import BinaryIO

import pyarrow as pa

from pruefstand.ingest.records_model import OldpLimits, Problem, RowBudget
from pruefstand.ingest.records_read import parquet_rows_local


def _virtual_bytes() -> int:
    """Current virtual size of this process (Linux ``/proc``); 0 when unavailable."""
    try:
        pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return 0
    return pages * resource.getpagesize()


def _limit_memory(extra: int) -> None:
    base = _virtual_bytes()
    if extra > 0 and base > 0:
        hard = resource.getrlimit(resource.RLIMIT_AS)[1]
        resource.setrlimit(resource.RLIMIT_AS, (base + extra, hard))


def _send(out: BinaryIO, event: tuple[object, ...]) -> None:
    pickle.dump(event, out, protocol=pickle.HIGHEST_PROTOCOL)
    out.flush()


def run(argv: list[str], out: BinaryIO) -> int:
    """Read the file named in ``argv[0]`` (JSON ``{path, columns, limits, left}``)."""
    spec = json.loads(argv[0])
    limits = OldpLimits(**spec["limits"])
    budget = RowBudget(spec["left"])
    problems: list[Problem] = []
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    _limit_memory(limits.max_parquet_memory_bytes)
    try:
        for number, row in parquet_rows_local(
            Path(spec["path"]), spec["columns"], limits, problems, budget
        ):
            while problems:
                _send(out, ("problem", problems.pop(0)))
            _send(out, ("row", number, row))
        while problems:
            _send(out, ("problem", problems.pop(0)))
    except MemoryError as error:
        _send(out, ("memory", f"{type(error).__name__}: {error}"[:200]))
        return 0
    _send(out, ("done", budget.left, budget.hit))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdout.buffer))
