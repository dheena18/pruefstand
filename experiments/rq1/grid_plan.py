"""RQ1 run plan (T7.3 S2/S5, offline): per-cell commands for the cells still to run, and cleanup.

Reads ``<out>/grid.json`` and each cell's ``rag.yaml`` (``run_grid.py``) and the cell states
(``grid_state.py``). For every pending or partial cell it writes ``<out>/<hash>/plan.json``: the
Qdrant collection ``rq1_<hash>``, the ``rag-demo index`` command (encoder from the cell's embed
engine), the ``pruefstand run --split rq1`` command and the cell's ``rerank.on_retrieve``. Nothing
is executed: the tier-2 stack runner of T6.2b runs the commands (index first, then the run).

    uv run python experiments/rq1/grid_plan.py --corpus corpus/<v> [--out runs/rq1] [--cleanup]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

# run as a script: import rq1.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rq1.grid_state import cleanup_argv, collection_name, resume_plan

ENCODERS = {"ollama": "ollama", "tei": "tei"}


def cell_plan(out: Path, rag_hash: str, corpus: Path, config: Path) -> dict[str, Any]:
    """The plan of one cell (index, then run), from its ``rag.yaml``.

    Raises:
        KeyError: the cell's embed engine is neither ``ollama`` nor ``tei``.
    """
    cell = out / rag_hash
    rag = yaml.safe_load((cell / "rag.yaml").read_text(encoding="utf-8"))
    collection = collection_name(rag_hash)
    return {
        "cell": rag_hash,
        "collection": collection,
        "rerank_on_retrieve": rag["rerank"]["on_retrieve"],
        "index_argv": [
            "uv", "run", "rag-demo", "index", "--corpus", str(corpus),
            "--encoder", ENCODERS[rag["embed"]["engine"]], "--config", str(cell / "rag.yaml"),
            "--collection", collection, "--no-alias",
        ],
        "run_argv": [
            "uv", "run", "pruefstand", "run", "--config", str(config), "--tier", "bench",
            "--split", "rq1", "--out", str(cell),
        ],
    }  # fmt: skip


def write_plans(out: Path, corpus: Path, config: Path) -> list[dict[str, Any]]:
    """Write ``plan.json`` for every cell still to run (grid order); return the plans."""
    plans = [cell_plan(out, h, corpus, config) for h in resume_plan(out)]
    for plan in plans:
        path = out / plan["cell"] / "plan.json"
        path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plans


def main(argv: Sequence[str] | None = None) -> int:
    """Print the plan (or the cleanup commands); executes nothing."""
    parser = argparse.ArgumentParser(description="RQ1 run plan (offline)")
    parser.add_argument("--out", type=Path, default=Path("runs/rq1"))
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("pruefstand.yaml"))
    parser.add_argument("--cleanup", action="store_true", help="print the drop commands only")
    args = parser.parse_args(argv)
    if args.cleanup:
        for drop in cleanup_argv(args.out):
            print(" ".join(drop))
        return 0
    plans = write_plans(args.out, args.corpus, args.config)
    for plan in plans:
        print(f"{plan['cell']}  rerank_on_retrieve={plan['rerank_on_retrieve']}")
    print(f"{len(plans)} cells to run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
