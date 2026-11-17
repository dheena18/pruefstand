"""GermanDPR test split -> the corpus/query JSONL pair of ``embed_bench.py`` (T3.1b S4).

The pinned parquet (``data/sources.yaml`` id ``germandpr``, CC BY 4.0, ``data/download.py --only
germandpr``) holds per question its positive and hard-negative contexts. The corpus is the union
of all contexts, keyed by the SHA-256 of the passage text (the pinned split's ``passage_id`` fields
are empty strings); each query's gold set is the keys of its positive contexts.
Output goes to ``data/derived/model_selection/`` (git-ignored, never committed).

    uv run python -m model_selection.germandpr_eval [--parquet ...] [--out ...]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import polars as pl
from model_selection.budget_inputs import ROOT

PARQUET = ROOT / "data/raw/hf/germandpr/plain_text/test/0000.parquet"
OUT = ROOT / "data/derived/model_selection"
CONTEXTS = ("positive_ctxs", "negative_ctxs", "hard_negative_ctxs")


def passage_key(text: str) -> str:
    """Stable passage id: the first 16 hex digits of the SHA-256 of the text.

    Examples:
        >>> passage_key("Trient.")
        '2c65690752ef5b2c'
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def to_eval(frame: pl.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(corpus, queries)`` rows: ``{"id", "text"}`` and ``{"id", "text", "gold"}``.

    Raises:
        ValueError: a question without a positive context.
    """
    corpus: dict[str, str] = {}
    queries: list[dict[str, Any]] = []
    for n, row in enumerate(frame.iter_rows(named=True)):
        for column in CONTEXTS:
            for text in (row[column] or {}).get("text") or []:
                corpus.setdefault(passage_key(str(text)), str(text))
        gold = [passage_key(str(t)) for t in (row["positive_ctxs"] or {}).get("text") or []]
        if not gold:
            msg = f"question {n} has no positive context"
            raise ValueError(msg)
        queries.append({"id": f"q{n:04d}", "text": str(row["question"]), "gold": gold})
    return [{"id": k, "text": v} for k, v in corpus.items()], queries


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows as UTF-8 JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    """Convert the pinned test split; print the counts."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--parquet", type=Path, default=PARQUET)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    corpus, queries = to_eval(pl.read_parquet(args.parquet))
    write_jsonl(args.out / "germandpr_test_corpus.jsonl", corpus)
    write_jsonl(args.out / "germandpr_test_queries.jsonl", queries)
    print(f"germandpr test: {len(queries)} queries, {len(corpus)} passages -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
