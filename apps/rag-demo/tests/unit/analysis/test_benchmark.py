"""Micro-benchmark: 10 000 real law chunks are tokenised in under 20 s on CPU (T3.3 S5)."""

import time

import pytest
from rd_support import slice_chunks

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder

CHUNKS = 10_000
LIMIT_S = 20.0


@pytest.mark.slow
def test_ten_thousand_chunks_in_under_twenty_seconds() -> None:
    texts = [str(row["text"]) for row in slice_chunks()]
    corpus = [texts[i % len(texts)] + f" {i}" for i in range(CHUNKS)]
    analyzer = GermanAnalyzer(compound_split=True, stemmer="snowball_de")
    encoder = SparseEncoder()
    started = time.perf_counter()
    for text in corpus:
        encoder.encode(analyzer.tokens(text))
    elapsed = time.perf_counter() - started
    print(f"benchmark: {CHUNKS} chunks in {elapsed:.1f} s")  # noqa: T201  (the logged result)
    assert elapsed < LIMIT_S
