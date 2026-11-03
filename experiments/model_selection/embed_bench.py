"""Embedding and reranker quality/latency helpers of the model benchmark (T3.1b S4).

Pure ranking maths (cosine, top-k, nDCG@10) plus thin callers for the native Ollama
``/api/embed`` and for
the ``rerank-cpu`` service (``POST /rerank``). Datasets are JSONL files given on the command line:
corpus rows ``{"id", "text"}`` and query rows ``{"id", "text", "gold": [ids]}``.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import numpy as np
from model_selection import stats
from model_selection.client import OllamaClient, load_entry

BATCH = 16
TOP = 10


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a UTF-8 JSONL file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def cosine_min(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """Smallest row-wise cosine between two embedding lists (must be >= 0.99 vs the reference).

    >>> cosine_min([[1.0, 0.0]], [[1.0, 0.0]])
    1.0
    """
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    cos = (x * y).sum(axis=1) / (np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1))
    return round(float(cos.min()), 6)


def top_k(
    query_vec: Sequence[float], doc_vecs: np.ndarray, ids: Sequence[str], k: int = TOP
) -> list[str]:
    """Ids of the ``k`` documents with the highest cosine to the query (ties broken by index)."""
    q = np.asarray(query_vec, dtype=float)
    sims = doc_vecs @ q / (np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(q))
    order = sorted(range(len(ids)), key=lambda i: (-sims[i], i))[:k]
    return [ids[i] for i in order]


def evaluate_dense(
    embed: Callable[[list[str], str], list[list[float]]],
    corpus: Sequence[Mapping[str, Any]],
    queries: Sequence[Mapping[str, Any]],
) -> list[float]:
    """Per-query nDCG@10 of a dense retriever; ``embed(texts, kind)`` gives one vector per text."""
    ids = [str(d["id"]) for d in corpus]
    docs: list[list[float]] = []
    for i in range(0, len(corpus), BATCH):
        docs += embed([str(d["text"]) for d in corpus[i : i + BATCH]], "doc")
    doc_vecs = np.asarray(docs, dtype=float)
    scores = []
    for q in queries:
        vec = embed([str(q["text"])], "query")[0]
        gold = {str(g) for g in q["gold"]}
        scores.append(stats.ndcg_at_k(top_k(vec, doc_vecs, ids), gold, TOP))
    return scores


def rerank_scores(url: str, query: str, texts: list[str], timeout_s: float = 120.0) -> list[float]:
    """Scores of ``texts`` for ``query`` from the ``rerank-cpu`` service, in input order."""
    resp = httpx.post(
        f"{url}/rerank", json={"query": query, "texts": texts, "truncate": True}, timeout=timeout_s
    )
    resp.raise_for_status()
    out = [0.0] * len(texts)
    for item in resp.json():
        out[item["index"]] = item["score"]
    return out


def latency_per_query(call: Callable[[int], object], n: int, concurrency: int) -> dict[str, float]:
    """p50/p95 seconds per query and wall seconds per query at the given concurrency.

    >>> latency_per_query(lambda i: None, 4, 2)["n"]
    4.0
    """

    def timed(i: int) -> float:
        start = perf_counter()
        call(i)
        return perf_counter() - start

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        times = list(pool.map(timed, range(n)))
    wall = perf_counter() - start
    return {
        "n": float(n),
        "p50_s": round(stats.percentile(times, 50), 4),
        "p95_s": round(stats.percentile(times, 95), 4),
        "mean_s": round(statistics.fmean(times), 4),
        "wall_per_query_s": round(wall / n, 4),
    }


def main(argv: list[str]) -> int:
    """Rank one catalogue embedding model on a corpus/query pair; print nDCG@10 with its 95 % CI."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--model", default="ollama/bge-m3")
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--queries", type=Path, required=True)
    args = ap.parse_args(argv)
    entry = load_entry(args.model)
    client = OllamaClient(lane="GPU0")
    scores = evaluate_dense(
        lambda texts, kind: client.embed(entry, texts, kind),
        read_jsonl(args.corpus),
        read_jsonl(args.queries),
    )
    mean, lo, hi = stats.bootstrap_ci(scores, seed=42)
    print(f"{entry.id} nDCG@10 {mean:.4f} [{lo:.4f}, {hi:.4f}] n={len(scores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
