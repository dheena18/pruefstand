"""Build the T5.3 calibration label sets 1-5 from the pinned T2.1 downloads (no LLM).

Usage::

    uv run python experiments/rq2/build_calibration_sets.py \
        --seed 1234 --out datasets/calibration/v1

Writes ``faithfulness_constructed``, ``correctness``, ``refusal`` and ``consistency`` as JSON lines
plus ``stats.json`` to ``--out``. The MEMERAG set (CC BY-NC 4.0, download-only) always goes to
``data/derived/memerag_de/`` (git-ignored), whatever ``--out`` says; only its counts appear in the
published ``stats.json``. Exit 0 on success, 1 when a source file is missing (run
``data/download.py --only <id>`` first).
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.calib_memerag import build_memerag
from rq2.calib_quad import build_consistency, build_correctness, sample_questions
from rq2.calib_rag import build_faithfulness_constructed, build_refusal
from rq2.calib_schema import CalibrationItem
from rq2.calib_sources import (
    GERMANQUAD_TEST,
    GERMANRAG,
    MEMERAG_DIR,
    load_germanquad,
    load_germanrag,
    load_memerag,
)
from rq2.calib_split import assign_calib_split
from rq2.calib_stats import hard_negatives_per_metric, set_stats, write_jsonl

MEMERAG_OUT = Path("data/derived/memerag_de")
LICENSE_CONFIG: dict[str, str] = {
    "faithfulness_memerag": "none (download_only, never published)",
    "faithfulness_constructed": "germanrag_derived",
    "correctness": "germanquad_derived",
    "refusal": "germanrag_derived",
    "consistency": "germanquad_derived",
}


def build_all(root: Path, seed: int) -> dict[str, list[CalibrationItem]]:
    """Build every set 1-5 from the downloads under ``root`` (split assigned)."""
    quad = load_germanquad(root / GERMANQUAD_TEST)
    rag = load_germanrag(root / GERMANRAG)
    questions = sample_questions(quad, seed)
    builders: dict[str, Callable[[], list[CalibrationItem]]] = {
        "faithfulness_memerag": lambda: build_memerag(load_memerag(root / MEMERAG_DIR)),
        "faithfulness_constructed": lambda: build_faithfulness_constructed(rag, seed),
        "correctness": lambda: build_correctness(questions, quad, seed),
        "refusal": lambda: build_refusal(rag, seed),
        "consistency": lambda: build_consistency(questions, quad, seed),
    }
    return {name: assign_calib_split(make(), seed) for name, make in builders.items()}


def write_all(
    sets: dict[str, list[CalibrationItem]], out: Path, memerag_out: Path
) -> dict[str, Any]:
    """Write every set and ``stats.json``; MEMERAG only to ``memerag_out``.

    Returns:
        The stats document that was written to ``out / "stats.json"``.
    """
    stats = {name: set_stats(items, LICENSE_CONFIG[name]) for name, items in sets.items()}
    for name, items in sets.items():
        target = memerag_out if name == "faithfulness_memerag" else out
        write_jsonl(items, target / f"{name}.jsonl")
    doc: dict[str, Any] = {
        "version": "v1",
        "sets": stats,
        "hard_negatives_per_metric": hard_negatives_per_metric(stats),
    }
    (out / "stats.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (memerag_out / "stats.json").write_text(
        json.dumps(stats["faithfulness_memerag"], indent=2) + "\n", encoding="utf-8"
    )
    return doc


def _summary(doc: dict[str, Any]) -> str:
    sets: dict[str, dict[str, Any]] = doc["sets"]
    lines = [
        f"{name}: n={s['n_items']} labels={s['labels']} split={s['calib_split']} "
        f"hard={s['hard_types']}"
        for name, s in sets.items()
    ]
    lines.append(f"hard negatives per metric: {doc['hard_negatives_per_metric']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point (see the module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--out", type=Path, default=Path("datasets/calibration/v1"))
    parser.add_argument("--root", type=Path, default=Path())
    args = parser.parse_args(argv)
    missing = [p for p in (GERMANQUAD_TEST, GERMANRAG, MEMERAG_DIR) if not (args.root / p).exists()]
    if missing:
        print(f"missing source(s): {', '.join(map(str, missing))}; run data/download.py first")
        return 1
    sets = build_all(args.root, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.root / MEMERAG_OUT).mkdir(parents=True, exist_ok=True)
    print(_summary(write_all(sets, args.out, args.root / MEMERAG_OUT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
