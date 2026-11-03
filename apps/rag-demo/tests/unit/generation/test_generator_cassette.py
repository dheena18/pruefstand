"""Replay of the answer recorded from the real A40 generator on native /api/chat (T3.6).

The cassette ``generate_ollama_622.yaml`` is recorded by the lead (``RAG_RECORD=1``,
``RECORD_OLLAMA_URL``, see ``live/test_record.py``); until it exists these tests skip.
"""

import pytest
from rd_support import CASSETTES, CONFIGS, REPO, hit

from rag_demo.config import load_config
from rag_demo.generation import OllamaChatGenerator
from rag_demo.models import Stats

CASSETTE = "generate_ollama_622.yaml"
pytestmark = pytest.mark.skipif(
    not (CASSETTES / CASSETTE).exists(), reason="cassette not recorded yet (lead action)"
)
CFG = load_config(CONFIGS / "rag.gpu.yaml", REPO / "infra" / "gpu" / "models.yaml")
QUESTION = "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"


@pytest.mark.default_cassette(CASSETTE)
@pytest.mark.vcr
async def test_the_recorded_a40_answer_has_no_think_block_and_cites_a_norm() -> None:
    stats = Stats()
    gen = OllamaChatGenerator(CFG, "http://llm-proxy:11500", stats=stats)
    out = await gen.answer(QUESTION, [hit("gii-bgb-622#1")])
    assert "<think>" not in out.answer
    assert out.citations
    assert out.refused is False
    assert out.prompt_tokens > 0
    assert out.completion_tokens > 0
