"""Recording scenarios for `make cassettes-contract` (`--record-mode=rewrite`): REAL exchanges only.

Skipped unless ``RAG_RECORD=1``; ``scripts/models/record_cassettes.sh`` runs them against the live
stack (llama.cpp generator and TEI), then the unit tests replay the cassettes.
"""

import os

import pytest
from rd_support import CONFIGS, hit

from rag_demo.config import load_config
from rag_demo.dense import TeiDenseEncoder
from rag_demo.generate import LlamaCppGenerator
from rag_demo.models import Stats

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RAG_RECORD") != "1", reason="set RAG_RECORD=1 to record"),
]
LLM = os.environ.get("RECORD_LLM_URL", "http://127.0.0.1:8080")
EMBED = os.environ.get("RECORD_EMBED_URL", "http://127.0.0.1:8090")
QUESTION = "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"


@pytest.mark.default_cassette("generate_smoke_622.yaml")
@pytest.mark.vcr
async def test_record_generator_answer() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    out = await LlamaCppGenerator(cfg, LLM, stats=Stats()).answer(QUESTION, [hit("gii-bgb-622#1")])
    assert out.answer


@pytest.mark.default_cassette("tei_query_e5.yaml")
@pytest.mark.vcr
def test_record_tei_query() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    vectors = TeiDenseEncoder(cfg.embed, EMBED).encode([QUESTION], kind="query")
    assert vectors.shape == (1, cfg.embed.dim)
