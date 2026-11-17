"""RQ1 grid resume and cleanup (T7.3 S5, offline part): which cells are done, what to drop.

A cell lives in ``runs/rq1/<rag config_hash>/`` (``run_grid.py``): ``rag.yaml`` plus the run
directories the stack runner writes there (``<run_id>/run.json``). A cell is

* ``done`` when one of its runs is complete (``run.json`` ``complete: true``, no ``infra_error``);
* ``partial`` when it has runs but none is complete (aborted, infra error): rerun it;
* ``pending`` when it has no run yet.

Each cell's index is the Qdrant collection ``rq1_<hash>``; ``--cleanup`` drops the collections of
``done`` cells only (a pending or partial cell may still need its index; never a gate collection).
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pruefstand.core.errors import ConfigError

Status = Literal["done", "partial", "pending"]
PREFIX = "rq1_"


def collection_name(rag_hash: str) -> str:
    """The Qdrant collection of one cell.

    Raises:
        ConfigError: ``rag_hash`` is not 16 lower-case hex digits (rag-demo's ``config_hash``).

    Examples:
        >>> collection_name("0047799c55b54988")
        'rq1_0047799c55b54988'
    """
    if len(rag_hash) != 16 or any(c not in "0123456789abcdef" for c in rag_hash):
        msg = f"not a rag-demo config hash: {rag_hash!r}"
        raise ConfigError(msg)
    return PREFIX + rag_hash


def _complete(run_json: Path) -> bool:
    try:
        manifest = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("complete") is True and manifest.get("infra_error") is None


def cell_status(cell: Path) -> Status:
    """``done``, ``partial`` or ``pending`` for one cell directory (missing directory: pending)."""
    runs = sorted(cell.glob("*/run.json")) if cell.is_dir() else []
    if any(_complete(run) for run in runs):
        return "done"
    return "partial" if runs else "pending"


def load_cells(out: Path) -> list[str]:
    """The cell hashes of ``<out>/grid.json``, in grid order.

    Raises:
        ConfigError: no ``grid.json`` (run ``run_grid.py`` first).
    """
    manifest = out / "grid.json"
    if not manifest.is_file():
        msg = f"{manifest} is missing: run experiments/rq1/run_grid.py first"
        raise ConfigError(msg)
    rows = json.loads(manifest.read_text(encoding="utf-8"))["cells"]
    return [str(row["rag_config_hash"]) for row in rows]


def resume_plan(out: Path) -> list[str]:
    """The cells still to run (pending first-time, partial again), in grid order."""
    return [h for h in load_cells(out) if cell_status(out / h) != "done"]


def cleanup_argv(out: Path) -> list[list[str]]:
    """One ``rag-demo index --drop`` command per ``done`` cell's collection (only ``rq1_*``)."""
    done = [h for h in load_cells(out) if cell_status(out / h) == "done"]
    return [["uv", "run", "rag-demo", "index", "--drop", collection_name(h)] for h in done]


def summary(out: Path) -> dict[Status, Sequence[str]]:
    """Cells by status (for the CLI's progress line)."""
    table: dict[Status, list[str]] = {"done": [], "partial": [], "pending": []}
    for h in load_cells(out):
        table[cell_status(out / h)].append(h)
    return dict(table)
