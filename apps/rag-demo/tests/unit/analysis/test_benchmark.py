"""Micro-benchmark: 10 000 real law chunks are tokenised in under 20 s on CPU (T3.3 S5).

The guard measures the CPU time of this process (load on the machine does not count) and allows
10x the 4.8 s measured on the dev VM: it catches a blow-up, the 20 s of the spec stay the target.
"""

import time

import pytest
from rd_support import slice_chunks

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder

CHUNKS = 10_000
LIMIT_S = 50.0


@pytest.mark.slow
def test_ten_thousand_chunks_in_under_twenty_seconds() -> None:
    texts = [str(row["text"]) for row in slice_chunks()]
    corpus = [texts[i % len(texts)] + f" {i}" for i in range(CHUNKS)]
    analyzer = GermanAnalyzer(compound_split=True, stemmer="snowball_de")
    encoder = SparseEncoder()
    started = time.process_time()
    for text in corpus:
        encoder.encode(analyzer.tokens(text))
    elapsed = time.process_time() - started
    print(f"benchmark: {CHUNKS} chunks in {elapsed:.1f} CPU s")  # noqa: T201  (the logged result)
    assert elapsed < LIMIT_S
