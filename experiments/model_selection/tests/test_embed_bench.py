"""T3.1b embed_bench.py tests: cosine, top-k, dense nDCG on a toy corpus, latency summary."""

import numpy as np
import pytest
from model_selection import embed_bench as eb


def test_cosine_min_detects_the_weakest_row() -> None:
    a = [[1.0, 0.0], [0.0, 1.0]]
    assert eb.cosine_min(a, a) == pytest.approx(1.0)
    assert eb.cosine_min(a, [[1.0, 0.0], [1.0, 1.0]]) == pytest.approx(0.707107, abs=1e-6)


def test_top_k_orders_by_cosine_then_index() -> None:
    docs = np.asarray([[0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    assert eb.top_k([1.0, 0.0], docs, ["a", "b", "c"], k=3) == ["b", "c", "a"]


def test_evaluate_dense_perfect_and_rank_three() -> None:
    corpus = [{"id": "d0", "text": "x0"}, {"id": "d1", "text": "x1"}, {"id": "d2", "text": "x2"}]
    vectors = {
        "x0": [1.0, 0.0, 0.0],
        "x1": [0.0, 1.0, 0.0],
        "x2": [0.0, 0.0, 1.0],
        "q": [0.0, 0.0, 1.0],
    }

    def embed(texts: list[str], kind: str) -> list[list[float]]:
        return [vectors[t] for t in texts]

    assert eb.evaluate_dense(embed, corpus, [{"id": "q1", "text": "q", "gold": ["d2"]}]) == [1.0]
    wrong = [
        {"id": "q2", "text": "q", "gold": ["d0"]}
    ]  # d0 and d1 tie after d2, index order puts d0 second
    assert eb.evaluate_dense(embed, corpus, wrong) == [pytest.approx(0.6309, abs=1e-3)]


def test_latency_summary_counts_queries() -> None:
    out = eb.latency_per_query(lambda i: None, 6, 2)
    assert out["n"] == 6.0
    assert out["p95_s"] >= out["p50_s"] >= 0.0
