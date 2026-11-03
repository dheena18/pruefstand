"""Qwen3 thinking switch, <think> stripping and chunk truncation (pure + cassette)."""

import pytest
from rd_support import CONFIGS, hit

from rag_demo.config import load_config
from rag_demo.generation import (
    OpenAICompatGenerator,
    build_prompt,
    strip_think,
    truncate_to_tokens,
)
from rag_demo.generation.llm_client import build_chat_request
from rag_demo.models import Stats

CFG = load_config(CONFIGS / "rag.yaml")
QWEN3 = CFG.model_copy(update={"generator": CFG.generator.model_copy(update={"family": "qwen3"})})


def test_qwen3_request_disables_thinking() -> None:
    body = build_chat_request([{"role": "user", "content": "Hallo"}], QWEN3)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["temperature"] == 0
    assert body["seed"] == 0
    assert body["max_tokens"] == 256


def test_non_qwen3_request_has_no_template_kwargs() -> None:
    other = CFG.model_copy(
        update={"generator": CFG.generator.model_copy(update={"family": "qwen"})}
    )
    assert "chat_template_kwargs" not in build_chat_request([], other)


def test_think_block_is_stripped_and_counted() -> None:
    text, count = strip_think("<think>abc</think>Die Frist …")
    assert (text, count) == ("Die Frist …", 1)
    assert strip_think("Keine Gedanken.") == ("Keine Gedanken.", 0)
    assert strip_think("<think>\nmehrzeilig\n</think>\n\nAntwort") == ("Antwort", 1)


def test_600_token_chunk_is_cut_to_256_in_the_prompt() -> None:
    long_text = " ".join(f"Wort{i}" for i in range(600))
    assert truncate_to_tokens(long_text, 256).split()[-1] == "Wort255"
    base = hit("gii-bgb-622#0")
    big = base.model_copy(update={"text": long_text})
    prompt = "\n".join(m["content"] for m in build_prompt("Frage?", [big], CFG))
    assert "Wort255" in prompt
    assert "Wort256" not in prompt


def test_short_text_is_untouched() -> None:
    assert truncate_to_tokens("Kurz.  Text", 256) == "Kurz.  Text"


@pytest.mark.default_cassette("generate_smoke_622.yaml")
@pytest.mark.vcr
async def test_recorded_real_answer_has_no_think_block() -> None:
    stats = Stats()
    out = await OpenAICompatGenerator(CFG, "http://llm.test:8080", stats=stats).answer(
        "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?",
        [hit("gii-bgb-622#1")],
    )
    assert "<think>" not in out.answer
    assert out.answer.strip()
    assert out.prompt_chunk_ids == ["gii-bgb-622#1"]
    assert stats.requests == 0  # the API counts requests, not the generator
