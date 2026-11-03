"""Owner scoring sheet of the German smoke (T3.1b S3): 10 generator answers, scored 0/1/2 by hand.

``owner_score_10.csv`` holds the columns ``question, answer, score`` (``score`` empty; the owner
fills 0, 1 or 2) followed by ``case_id, kind, context`` for orientation. The ten items come from
the generator's answers of a committed run, picked with a fixed seed round-robin over the kinds
so every category is seen at least once.

    PYTHONPATH=experiments python -m model_selection.owner_sheet \
        --answers experiments/model_selection/results/2026-11-03_answers.jsonl
"""

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from model_selection.bench_cases import CASES_PATH, Case, load_cases

HERE = Path(__file__).resolve().parent
GENERATOR_ID = "ollama/qwen3.8:27b-q8_0"
OUT = HERE / "owner_score_10.csv"
FIELDS = ("question", "answer", "score", "case_id", "kind", "context")
SEED = 20261103


def pick_items(
    rows: Sequence[dict[str, Any]], n: int = 10, seed: int = SEED
) -> list[dict[str, Any]]:
    """Pick ``n`` rows reproducibly, spread over the ``kind`` values.

    Kinds are visited in a seeded random order, one row per kind and round, a seeded random row
    within the kind, until ``n`` rows are chosen (or the rows run out).

    >>> rows = [{"case": f"{k}{i}", "kind": k} for k in "ab" for i in range(3)]
    >>> [r["kind"] for r in pick_items(rows, 4, seed=1)]
    ['a', 'b', 'a', 'b']
    """
    rng = np.random.default_rng(seed)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: str(r["case"])):
        by_kind.setdefault(str(row["kind"]), []).append(row)
    kinds = sorted(by_kind)
    rng.shuffle(kinds)
    for pool in by_kind.values():
        rng.shuffle(pool)
    picked: list[dict[str, Any]] = []
    while len(picked) < n and any(by_kind.values()):
        for kind in kinds:
            if by_kind[kind] and len(picked) < n:
                picked.append(by_kind[kind].pop())
    return picked


def sheet_rows(picked: Sequence[dict[str, Any]], cases: Sequence[Case]) -> list[dict[str, str]]:
    """CSV rows (``score`` empty) for the picked answers, joined with their cases."""
    by_id = {c.id: c for c in cases}
    return [
        {
            "question": by_id[str(p["case"])].question,
            "answer": str(p["answer"]),
            "score": "",
            "case_id": str(p["case"]),
            "kind": str(p["kind"]),
            "context": by_id[str(p["case"])].context,
        }
        for p in picked
    ]


def build(answers_path: Path, out: Path = OUT, cases_path: Path = CASES_PATH) -> int:
    """Write the sheet from the generator rows of ``answers_path``; return the row count."""
    lines = answers_path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(ln) for ln in lines if ln.strip()]
    gen = [r for r in rows if r["model"] == GENERATOR_ID]
    sheet = sheet_rows(pick_items(gen), load_cases(cases_path))
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sheet)
    return len(sheet)


def main(argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--answers", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    print(f"wrote {build(args.answers, args.out)} rows to {args.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
