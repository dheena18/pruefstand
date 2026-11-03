"""Recording scenarios for `make cassettes-contract` (`--record-mode=rewrite`): REAL exchanges only.

Skipped unless ``RAG_RECORD=1``; ``scripts/models/record_cassettes.sh`` runs them against the live
stack (llama.cpp generator and TEI), then the unit tests replay the cassettes. The reranker
cassette needs a running ``rerank-cpu`` (``RECORD_RERANK_URL``; ``make cassettes-rerank``).
"""

import os

import pytest
from rd_support import CONFIGS, REPO, RERANK_QUERY, hit, rerank_input

from rag_demo.config import load_config
from rag_demo.generation import OllamaChatGenerator, OpenAICompatGenerator
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.models import Stats
from rag_demo.retrieval.rerank import CrossEncoderReranker

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RAG_RECORD") != "1", reason="set RAG_RECORD=1 to record"),
]
LLM = os.environ.get("RECORD_LLM_URL", "http://127.0.0.1:8080")
EMBED = os.environ.get("RECORD_EMBED_URL", "http://127.0.0.1:8090")
RERANK = os.environ.get("RECORD_RERANK_URL", "http://127.0.0.1:18201")
OLLAMA = os.environ.get("RECORD_OLLAMA_URL", "http://127.0.0.1:11434")
QUESTION = "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"


@pytest.mark.default_cassette("generate_smoke_622.yaml")
@pytest.mark.vcr
async def test_record_generator_answer() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    out = await OpenAICompatGenerator(cfg, LLM, stats=Stats()).answer(
        QUESTION, [hit("gii-bgb-622#1")]
    )
    assert out.answer


@pytest.mark.default_cassette("generate_ollama_622.yaml")
@pytest.mark.vcr
async def test_record_ollama_generator_answer() -> None:
    """The real A40 generator on native /api/chat (lead records it under the lock)."""
    cfg = load_config(CONFIGS / "rag.gpu.yaml", REPO / "infra" / "gpu" / "models.yaml")
    out = await OllamaChatGenerator(cfg, OLLAMA, stats=Stats()).answer(
        QUESTION, [hit("gii-bgb-622#1")]
    )
    assert out.answer


@pytest.mark.default_cassette("tei_query_e5.yaml")
@pytest.mark.vcr
def test_record_tei_query() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    vectors = TeiDenseEncoder(cfg.embed, EMBED).encode([QUESTION], kind="query")
    assert vectors.shape == (1, cfg.embed.dim)


@pytest.mark.default_cassette("rerank_622.yaml")
@pytest.mark.vcr
def test_record_rerank_scores() -> None:
    """The real ``rerank-cpu`` (no auth) scoring the ten fused hits of ``rerank_input``."""
    reranker = CrossEncoderReranker(RERANK, max_passage_tokens=256, timeout_s=300.0)
    out = reranker.rerank(RERANK_QUERY, rerank_input(), top_n=10)
    assert out[0].chunk_id == "gii-bgb-622#1"
