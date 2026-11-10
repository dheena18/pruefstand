"""Parent side of the parquet reader process (T2.3a; hardened by review F5, D1122).

:func:`parquet_rows` starts :mod:`pruefstand.ingest.records_child` with a minimal environment and
reads its JSON event lines (:mod:`~pruefstand.ingest.records_wire`; nothing is unpickled): each
line, the total output, the rows (never more than the budget sent), texts, list items per row and
nesting are capped, every event is checked for its exact shape, and the row budget the child
reports back is accepted only when it is not more than what was sent minus the rows received. A
child over its wall time is killed and ends the file with one counted ``read_timeout`` (its CPU
limit ends it the same way).
"""

import dataclasses
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from pathlib import Path
from typing import IO

from pruefstand.core.logging import get_logger
from pruefstand.ingest.records_model import OldpLimits, Problem, RowBudget
from pruefstand.ingest.records_read import parquet_rows_local
from pruefstand.ingest.records_wire import WireError, decode

_log = get_logger(__name__)
_KEEP_ENV = ("PATH", "HOME")
_KEEP_PREFIXES = ("ARROW_", "MALLOC_", "OPENBLAS_", "OMP_", "MKL_")
# one malloc arena and the system allocator: per-thread arenas reserve address space that the
# address-space limit of the child would count; numpy would start one BLAS thread per core
_CHILD_SETTINGS = {
    "ARROW_DEFAULT_MEMORY_POOL": "system",
    "MALLOC_ARENA_MAX": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: PATH, HOME and the allocator/thread variables, no secrets."""
    kept = {k: v for k, v in environ.items() if k in _KEEP_ENV or k.startswith(_KEEP_PREFIXES)}
    return {**kept, **_CHILD_SETTINGS}


class Watch:
    """Wall-time budget of the reader that counts only the time spent waiting for it (F7).

    ``waiting`` / ``consumed`` bracket each read; time the caller spends on a yielded row is not
    counted. ``left`` is pure (clock injected); the thread in :func:`parquet_rows` uses it.
    """

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds, self._clock = seconds, clock
        self._used = 0.0
        self._since: float | None = None
        self.expired = threading.Event()
        self.changed = threading.Condition()

    def waiting(self) -> None:
        """A read starts."""
        with self.changed:
            self._since = self._clock()
            self.changed.notify_all()

    def consumed(self) -> None:
        """A read ended; its time is charged."""
        with self.changed:
            if self._since is not None:
                self._used += self._clock() - self._since
            self._since = None
            self.changed.notify_all()

    def left(self) -> float | None:
        """Seconds left while a read is running, None while the caller holds a row."""
        if self._since is None:
            return None
        return self.seconds - self._used - (self._clock() - self._since)


def _guard(watch: Watch, stop: Callable[[], None], done: threading.Event) -> None:
    """Thread body: call ``stop`` once the reads have used up the wall-time budget."""
    with watch.changed:
        while not done.is_set():
            left = watch.left()
            if left is not None and left <= 0:
                watch.expired.set()
                stop()
                return
            watch.changed.wait(None if left is None else left)


def _line(stream: IO[bytes], cap: int) -> bytes | None:
    """One event line, None at the end of the stream (a cut last line is the end too)."""
    line = stream.readline(cap + 1)
    if len(line) > cap:
        msg = f"the reader sent a line of more than {cap} bytes"
        raise WireError(msg)
    return line if line.endswith(b"\n") else None


def events(
    stream: IO[bytes],
    path: Path,
    limits: OldpLimits,
    problems: list[Problem],
    budget: RowBudget,
    *,
    watch: Watch | None = None,
) -> Generator[tuple[int, dict[str, object]], None, str]:
    """Yield the rows of the child's event stream; problems and the budget are applied.

    Returns how the stream ended: ``"done"``, ``"memory"``, ``"protocol"`` (one counted
    ``reader_protocol`` problem) or ``"eof"`` (the child died or was killed; the caller says why).
    The budget is charged at least the rows received.
    """
    sent, received, total = budget.left, 0, 0
    cap = 2 * limits.max_record_bytes + 1024 * 1024
    try:
        while (line := _watched_line(stream, cap, watch)) is not None:
            total += len(line)
            event = _decode(line, total, limits)
            tag, number, row = event[0], event[1], event[2] if len(event) > 2 else None
            if tag == "row" and isinstance(number, int) and isinstance(row, dict):
                received = _count_row(received, sent)
                budget.left = sent - received
                yield number, row
            elif tag == "problem":
                problems.append(Problem(str(event[1]), str(event[2]), str(event[3])))
            elif tag == "warning":
                _log.warning("parquet_reader_unlimited", file=path.name, reason=event[1])
            elif tag == "memory":
                mib = limits.max_parquet_memory_bytes // (1024 * 1024)
                detail = f"{event[1]}; the reader may use {mib} MiB more than it starts with"
                problems.append(Problem(path.name, "memory_limit", detail))
                return "memory"
            elif tag == "done":
                _accept_budget(event, sent - received, budget)
                return "done"
    except WireError as error:
        problems.append(Problem(path.name, "reader_protocol", str(error)))
        return "protocol"
    return "eof"


def _watched_line(stream: IO[bytes], cap: int, watch: Watch | None) -> bytes | None:
    if watch is None:
        return _line(stream, cap)
    watch.waiting()
    try:
        return _line(stream, cap)
    finally:
        watch.consumed()


def _decode(line: bytes, total: int, limits: OldpLimits) -> tuple[object, ...]:
    if total > limits.max_parquet_output_bytes:
        msg = f"the reader sent more than {limits.max_parquet_output_bytes} bytes"
        raise WireError(msg)
    return decode(line, max_text=limits.max_record_bytes, max_items=limits.max_list_elements)


def _count_row(received: int, sent: int) -> int:
    if received >= sent:
        msg = f"the reader sent more than the {sent} rows it was allowed"
        raise WireError(msg)
    return received + 1


def _accept_budget(event: tuple[object, ...], most: int, budget: RowBudget) -> None:
    left, hit = event[1], event[2]
    if not isinstance(left, int) or isinstance(left, bool) or not 0 <= left <= most:
        msg = f"the reader reported {left!r} rows left, more than {most} or invalid"
        raise WireError(msg)
    budget.left, budget.hit = left, bool(hit)


def parquet_rows(
    path: Path,
    columns: Sequence[str],
    limits: OldpLimits,
    problems: list[Problem],
    budget: RowBudget,
) -> Iterator[tuple[int, dict[str, object]]]:
    """Read a parquet file in a child process with hard memory, CPU and wall limits.

    Same rows and problems as :func:`~pruefstand.ingest.records_read.parquet_rows_local`. When
    the child runs out of memory (or dies), the file ends with one counted ``memory_limit``
    problem; over its CPU or wall time with one ``read_timeout``; the machine is not affected.
    ``limits.max_parquet_memory_bytes == 0`` reads in this process.
    """
    if limits.max_parquet_memory_bytes <= 0:
        yield from parquet_rows_local(path, columns, limits, problems, budget)
        return
    spec = {
        "path": str(path),
        "columns": list(columns),
        "limits": dataclasses.asdict(limits),
        "left": budget.left,
    }
    # -I: isolated mode, so a file named like a standard module in the working directory is never
    # imported by the reader
    command = [sys.executable, "-I", "-m", "pruefstand.ingest.records_child", json.dumps(spec)]
    with subprocess.Popen(  # noqa: S603 (our own module, arguments are data)
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=child_env(os.environ),
        start_new_session=True,  # its own process group: killpg also ends anything it started
    ) as child:
        watch, done = Watch(limits.max_parquet_wall_seconds), threading.Event()
        guard = threading.Thread(
            target=_guard, args=(watch, lambda: _kill_group(child), done), daemon=True
        )
        guard.start()
        try:
            yield from _child_rows(child, path, limits, problems, budget, watch=watch)
        finally:
            done.set()
            with watch.changed:
                watch.changed.notify_all()
            _kill_group(child)


def _kill_group(child: "subprocess.Popen[bytes]") -> None:
    """SIGKILL the reader's process group (the reader and anything it started).

    Skipped once the reader has been reaped: its pid (= process group id) may be reused.
    """
    if child.returncode is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        child.kill()


def _child_rows(
    child: "subprocess.Popen[bytes]",
    path: Path,
    limits: OldpLimits,
    problems: list[Problem],
    budget: RowBudget,
    *,
    watch: Watch,
) -> Iterator[tuple[int, dict[str, object]]]:
    assert child.stdout is not None  # noqa: S101 (PIPE was requested)
    end = yield from events(child.stdout, path, limits, problems, budget, watch=watch)
    if end != "eof":
        return
    code = child.wait()
    if watch.expired.is_set() or code == -signal.SIGXCPU:
        why = "wall time" if watch.expired.is_set() else "CPU time"
        problems.append(Problem(path.name, "read_timeout", f"reader stopped: over its {why} limit"))
        return
    detail = f"reader process ended with exit code {code} (memory limit or crash)"
    problems.append(Problem(path.name, "memory_limit", detail))
