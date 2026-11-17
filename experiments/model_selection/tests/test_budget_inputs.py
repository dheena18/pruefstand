"""T3.1b S5 inputs: generator output cap from rag.gpu.yaml, measured reranker lane (or assumed)."""

from pathlib import Path

import pytest
from model_selection import budget as b
from model_selection import rerank_bench as rb
from model_selection.budget_inputs import (
    ASSUMED_RERANK_S,
    GPU_CONFIG,
    generator_out_tokens,
    rerank_input,
)


def test_the_output_cap_comes_from_rag_gpu_yaml(tmp_path: Path) -> None:
    assert generator_out_tokens() == 256  # the committed tier-2 profile
    other = tmp_path / "rag.yaml"
    other.write_text("generation: {max_tokens: 512}\n", encoding="utf-8")
    assert generator_out_tokens(other) == 512
    other.write_text("max_tokens: 128\n", encoding="utf-8")
    assert generator_out_tokens(other) == 128
    other.write_text("generation: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_tokens"):
        generator_out_tokens(other)
    assert GPU_CONFIG.is_file()


def test_the_rerank_lane_uses_the_latest_measurement_else_the_assumption(tmp_path: Path) -> None:
    path = tmp_path / "rerank_latency.csv"
    assert rerank_input(path) == rb_input(ASSUMED_RERANK_S, "assumed")
    rows: list[dict[str, object]] = [
        {"date": "2026-11-17T10:00", "model": "m", "top": 10, "concurrency": 1, "n": 5,
         "p50_s": 0.9, "p95_s": 1.1, "mean_s": 0.95, "wall_per_query_s": 0.96},
        {"date": "2026-11-18T10:00", "model": "m", "top": 10, "concurrency": 1, "n": 5,
         "p50_s": 0.7, "p95_s": 0.9, "mean_s": 0.75, "wall_per_query_s": 0.76},
        {"date": "2026-11-18T10:00", "model": "m", "top": 10, "concurrency": 4, "n": 5,
         "p50_s": 2.0, "p95_s": 2.5, "mean_s": 2.1, "wall_per_query_s": 0.55},
    ]  # fmt: skip
    rb.append_rows(rows, path)
    assert rerank_input(path) == rb_input(0.76, "measured")
    assert rerank_input(path, concurrency=4).seconds_per_query == 0.55


def rb_input(seconds: float, source: str) -> object:
    from model_selection.budget_inputs import RerankInput  # noqa: PLC0415

    return RerankInput(seconds, 1, source)  # type: ignore[arg-type]  # literal checked by equality


def test_the_reranker_verdict_follows_the_measured_input(tmp_path: Path) -> None:
    path = tmp_path / "rerank_latency.csv"
    row: dict[str, object] = {"date": "2026-11-18T10:00", "model": "m", "top": 10,
                              "concurrency": 1, "n": 5, "p50_s": 0, "p95_s": 0,
                              "mean_s": 0}  # fmt: skip
    rb.append_rows([row | {"wall_per_query_s": 1.6}], path)
    slow = rerank_input(path)
    assert b.rerank_verdict(790, slow.seconds_per_query).robust_pr_reranker == "off"  # 21.1 min
    rb.append_rows([row | {"date": "2026-11-19T10:00", "wall_per_query_s": 1.5}], path)
    assert b.rerank_verdict(790, rerank_input(path).seconds_per_query).robust_pr_reranker == "on"


def test_bench_requests_are_seeded_and_ten_passages_each() -> None:
    queries, passages = rb.load_queries(), rb.load_passages()
    assert len(queries) >= 100
    assert len(passages) >= 10
    first = rb.requests(queries, passages, 5)
    assert first == rb.requests(queries, passages, 5)
    assert all(len(texts) == 10 and len(set(texts)) == 10 for _, texts in first)
    with pytest.raises(ValueError, match="at least 10"):
        rb.requests(queries, passages[:9], 1)
