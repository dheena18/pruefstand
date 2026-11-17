"""Reranker CPU latency on the VM (T3.1b S4): top 10 passages per query, 256 tokens, batched.

Queries are the German smoke questions (``questions_de.jsonl``), passages the public corpus slice
(``corpus/slice_v1``); latency does not need gold labels. Each query sends 10 passages (seeded
choice) in ONE ``POST /rerank`` (``truncate: true``: the service cuts them to 256 tokens), at
concurrency 1 and 4. Rows are appended to ``results/rerank_latency.csv``.

    uv run python -m model_selection.rerank_bench --url http://127.0.0.1:18201 [--n 100]
"""

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from model_selection.budget_inputs import RERANK_CSV, ROOT
from model_selection.embed_bench import latency_per_query, rerank_scores

QUESTIONS = Path(__file__).resolve().parent / "questions_de.jsonl"
CORPUS = ROOT / "corpus" / "slice_v1"
TOP = 10
COLUMNS = [
    "date",
    "model",
    "top",
    "concurrency",
    "n",
    "p50_s",
    "p95_s",
    "mean_s",
    "wall_per_query_s",
]


def load_queries(path: Path = QUESTIONS) -> list[str]:
    """The ``question`` texts of the smoke set, in file order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [str(json.loads(line)["question"]) for line in lines if line.strip()]


def load_passages(root: Path = CORPUS) -> list[str]:
    """The chunk texts of the public corpus slice, in file order."""
    out: list[str] = []
    for path in sorted(root.glob("*.chunks.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out += [str(json.loads(line)["text"]) for line in lines if line.strip()]
    return out


def requests(
    queries: list[str], passages: list[str], n: int, seed: int = 1234
) -> list[tuple[str, list[str]]]:
    """``n`` (query, 10 passages) pairs; queries cycle, passages are a seeded choice per request.

    Raises:
        ValueError: fewer than ``TOP`` passages.
    """
    if len(passages) < TOP:
        msg = f"need at least {TOP} passages, got {len(passages)}"
        raise ValueError(msg)
    rng = np.random.default_rng(seed)
    picks = [rng.choice(len(passages), size=TOP, replace=False) for _ in range(n)]
    return [
        (queries[i % len(queries)], [passages[int(j)] for j in pick])
        for i, pick in enumerate(picks)
    ]


def append_rows(rows: list[dict[str, object]], path: Path = RERANK_CSV) -> None:
    """Append rows to the latency CSV (header for a new file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str]) -> int:
    """Measure and append one row per concurrency."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--url", required=True, help="rerank-cpu base URL (dev stack: port 18201)")
    ap.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    args = ap.parse_args(argv)
    reqs = requests(load_queries(), load_passages(), args.n)
    rerank_scores(args.url, reqs[0][0], reqs[0][1])  # warm-up, not timed
    date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    rows: list[dict[str, object]] = []
    for c in args.concurrency:
        lat = latency_per_query(lambda i: rerank_scores(args.url, *reqs[i]), args.n, c)
        rows.append({"date": date, "model": args.model, "top": TOP, "concurrency": c} | lat)
        print(f"concurrency {c}: {lat}")
    append_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
