"""Run directory of ``scripts/generate_qa.py``: the resume ledger and the atomic output files.

The ledger (``ledger.jsonl``) holds one line per finished unit: ``ok`` with its candidate, or
``invalid`` (the answer stayed invalid after the repair). A unit that stopped early (quota,
budget, outage) has no line, so the next run sends it again. Lines are appended and flushed as
units finish, so a killed run loses at most the unit in flight. Output files are written to a
temporary name and renamed.
"""

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from pruefstand.core.models.dataset import QACandidate

LEDGER = "ledger.jsonl"
CANDIDATES = "candidates.jsonl"
CROSS_CHECK = "cross_check.jsonl"
VALIDATION = "validation.jsonl"
SUMMARY = "summary.json"


@dataclass(frozen=True)
class Entry:
    """One finished unit: ``candidate`` is None for an invalid answer."""

    key: str
    candidate: QACandidate | None


def dump_line(model: BaseModel) -> str:
    """Return the canonical JSON line of a model (sorted keys, UTF-8, no ASCII escapes)."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write ``lines`` to ``path`` by writing a temporary file and renaming it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(line + "\n" for line in lines)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def read_ledger(run_dir: Path) -> dict[str, Entry]:
    """Read the ledger; a damaged line (for example the last one of a killed run) is ignored."""
    path = run_dir / LEDGER
    entries: dict[str, Entry] = {}
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            cand = row["candidate"]
            entries[str(row["key"])] = Entry(
                str(row["key"]), QACandidate.model_validate(cand) if cand is not None else None
            )
        except (ValueError, KeyError, TypeError, ValidationError):
            continue
    return entries


def append_entry(run_dir: Path, key: str, candidate: QACandidate | None) -> None:
    """Append one finished unit to the ledger and flush it to disk."""
    run_dir.mkdir(parents=True, exist_ok=True)
    row: dict[str, object] = {
        "key": key,
        "status": "ok" if candidate else "invalid",
        "candidate": candidate.model_dump(mode="json") if candidate else None,
    }
    with (run_dir / LEDGER).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def planned_candidates(entries: dict[str, Entry], keys: Sequence[str]) -> list[QACandidate]:
    """The finished candidates of the planned units, in plan order."""
    return [c for k in keys if (e := entries.get(k)) is not None and (c := e.candidate) is not None]


def read_candidates(run_dir: Path) -> list[QACandidate]:
    """Read ``candidates.jsonl`` of a run."""
    path = run_dir / CANDIDATES
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return [QACandidate.model_validate_json(line) for line in lines if line.strip()]
