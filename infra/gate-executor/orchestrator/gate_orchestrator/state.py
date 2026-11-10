"""Executor state: ``state/processed.jsonl`` (D102, D288) and ``state/nightly_counter`` (D299).

``processed.jsonl`` is a record, never a filter: every owner dispatch runs. One JSON line per
finished job ``{pr, head_sha, dispatch_run_id, result, run_id, at}``; lines with the same
``(pr, head_sha, dispatch_run_id)`` collapse to the last one. The nightly counter is a single
integer (``k = counter mod 3``), written atomically (temp file + rename) and incremented only after
a completed nightly (``ok`` or ``failed``, P4.4).
"""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from gate_orchestrator.models import ProcessedEntry
from gate_orchestrator.window import COMPLETED

COUNTER_ENV = "PRUEFSTAND_NIGHTLY_COUNTER"


def load_processed(path: Path) -> list[ProcessedEntry]:
    """Read ``processed.jsonl``; a missing file is empty.

    Args:
        path: the state file.

    Returns:
        The entries in file order, duplicates of ``(pr, head_sha, dispatch_run_id)`` collapsed to
        the last line.

    Raises:
        ValueError: a line is not a valid entry; the message names the file and line number.
    """
    if not path.exists():
        return []
    entries: dict[tuple[int, str, int], ProcessedEntry] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = ProcessedEntry.model_validate_json(line)
        except ValidationError as err:
            msg = f"{path}:{number}: corrupt processed.jsonl line"
            raise ValueError(msg) from err
        key = (entry.pr, entry.head_sha, entry.dispatch_run_id)
        entries.pop(key, None)
        entries[key] = entry
    return list(entries.values())


def append_processed(path: Path, entry: ProcessedEntry) -> None:
    """Append one entry as a JSON line (parents created, flushed to disk)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def nightly_counter_path(env: Mapping[str, str]) -> Path:
    """``$PRUEFSTAND_NIGHTLY_COUNTER``, else ``$PRUEFSTAND_HOME/state/nightly_counter`` (D322).

    Raises:
        ValueError: neither variable is set.
    """
    named = env.get(COUNTER_ENV, "")
    if named:
        return Path(named)
    home = env.get("PRUEFSTAND_HOME", "")
    if not home:
        msg = f"{COUNTER_ENV} and PRUEFSTAND_HOME are unset"
        raise ValueError(msg)
    return Path(home) / "state" / "nightly_counter"


def read_counter(path: Path) -> int:
    """The counter value; a missing file is 0.

    Raises:
        ValueError: the file does not hold one non-negative integer.
    """
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        msg = f"{path}: nightly counter is not a non-negative integer"
        raise ValueError(msg)
    return int(text)


def increment_counter(path: Path) -> int:
    """Write ``read_counter(path) + 1`` atomically (temp file + rename); return the new value."""
    value = read_counter(path) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".nightly_counter.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return value


def finish_nightly(path: Path, status: str) -> int:
    """Increment the counter only for a completed nightly (``ok``/``failed``); return the value.

    ``skipped: …`` and ``aborted: …`` leave it unchanged, so that night's block repeats (P4.4).
    """
    if status in COMPLETED:
        return increment_counter(path)
    return read_counter(path)
