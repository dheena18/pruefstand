"""``OllamaDenseEncoder`` against the real Ollama ``bge-m3`` on GPU0 (T3.4, run under the GPU lock).

    pruefstand-lock uv run pytest -m gpu apps/rag-demo/tests/gpu/test_ollama_embed.py -v

Needs day mode loaded (``make gpu-up``), the tunnel up and ``OLLAMA_GPU0_URL`` set; the truncation
test also needs ``RAG_EMBED_TOKENIZER`` (``make fetch-tokenizer``).
"""

import os
from pathlib import Path

import numpy as np
import pytest
from rd_support import CONFIGS, REPO

from rag_demo.catalogue import load_catalogue
from rag_demo.config import load_config
from rag_demo.index.encoders import OllamaDenseEncoder
from rag_demo.wiring import build_dense

pytestmark = pytest.mark.gpu
CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
URL = os.environ.get("OLLAMA_GPU0_URL", "http://127.0.0.1:11434")


def _encoder() -> OllamaDenseEncoder:
    cfg = load_config(CONFIGS / "rag.gpu.yaml", CATALOGUE)
    tokenizer = os.environ.get("RAG_EMBED_TOKENIZER")
    encoder = build_dense(
        cfg,
        URL,
        catalogue=load_catalogue(CATALOGUE),
        tokenizer=Path(tokenizer) if tokenizer else None,
    )
    assert isinstance(encoder, OllamaDenseEncoder)
    return encoder


def test_bge_m3_gives_1024_unit_vectors_and_the_kuendigung_ordering() -> None:
    vectors = _encoder().encode(["Kündigung", "Kündigungsfrist", "Datenschutz"], kind="passage")
    assert vectors.shape == (3, 1024)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    assert float(vectors[0] @ vectors[1]) > float(vectors[0] @ vectors[2])


@pytest.mark.skipif(not os.environ.get("RAG_EMBED_TOKENIZER"), reason="needs RAG_EMBED_TOKENIZER")
def test_a_9000_token_passage_is_embedded_and_counted_as_truncated() -> None:
    encoder = _encoder()
    out = encoder.encode([" ".join(["Arbeitnehmerkündigung"] * 4000)], kind="passage")
    assert out.shape == (1, 1024)
    assert encoder.truncated == 1
