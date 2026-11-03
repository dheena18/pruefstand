"""``TeiDenseEncoder`` against the real TEI CPU service of the ``live`` stack (T3.4).

Needs ``make up PROFILES="core live dev" WAIT=1``; the URL comes from ``RAG_EMBED_URL`` (default
``http://127.0.0.1:$EMBED_HOST_PORT``, 8090 without the dev offset).
"""

import os

import numpy as np
import pytest
from rd_support import CONFIGS

from rag_demo.config import load_config
from rag_demo.index.encoders import TeiDenseEncoder

pytestmark = pytest.mark.live
URL = os.environ.get(
    "RAG_EMBED_URL", f"http://127.0.0.1:{os.environ.get('EMBED_HOST_PORT', '8090')}"
)


def test_tei_vectors_have_the_configured_dimension_and_order_by_meaning() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    vectors = TeiDenseEncoder(cfg.embed, URL).encode(
        ["Kündigung", "Kündigungsfrist", "Datenschutz"], kind="passage"
    )
    assert vectors.shape == (3, cfg.embed.dim)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    assert float(vectors[0] @ vectors[1]) > float(vectors[0] @ vectors[2])
