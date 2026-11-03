"""Prompt budget, generator tokenizer and ``prompt_overflow`` (AI13-05, D307)."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx
from rd_support import CONFIGS, REPO, hit

from rag_demo import wiring
from rag_demo.catalogue import load_catalogue
from rag_demo.config import Settings, load_config
from rag_demo.generation import OllamaChatGenerator, build_prompt
from rag_demo.generation import budget as budget_mod
from rag_demo.generation.budget import (
    count_prompt_tokens,
    fit_hits,
    is_overflow,
    prompt_budget,
)
from rag_demo.models import Hit, Stats

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
CFG = load_config(CONFIGS / "rag.gpu.yaml", CATALOGUE)
URL = "http://llm-proxy:11500/api/chat"
IDS = ["gii-bgb-622#1", "gii-kschg-1#0", "gii-bgb-620#0", "gii-bgb-621#0"]


def spy_counter(seen: list[str]) -> Callable[[str], int]:
    def count(text: str) -> int:
        seen.append(text)
        return len(text.split())

    return count


def _hits() -> list[Hit]:
    return [hit(cid, rank) for rank, cid in enumerate(IDS, start=1)]


def _reply(prompt_eval_count: int) -> httpx.Response:
    body = {
        "model": "qwen3.8:27b-q8_0",
        "message": {"content": "Einen Monat (§ 622 BGB)."},
        "prompt_eval_count": prompt_eval_count,
        "eval_count": 5,
    }
    return httpx.Response(200, json=body)


def test_budget_is_num_ctx_minus_num_predict_and_tier_1_has_none() -> None:
    assert prompt_budget(CFG) == 8192 - 256
    assert prompt_budget(load_config(CONFIGS / "rag.yaml")) is None


def test_the_prompt_count_wraps_the_messages_like_the_chat_template() -> None:
    seen: list[str] = []
    messages = build_prompt("Frage?", _hits()[:1], CFG)
    count_prompt_tokens(messages, spy_counter(seen), CFG)
    (text,) = seen
    assert text.startswith("<|im_start|>system\n")
    assert "<|im_start|>user\n" in text
    assert text.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_overflow_rule() -> None:
    assert is_overflow(1030, 1000, 7936) is True
    assert is_overflow(1010, 1000, 7936) is False
    assert is_overflow(7936, 7936, 7936) is True
    assert is_overflow(7935, None, 7936) is False


@respx.mock
@pytest.mark.parametrize(("factor", "overflow"), [(1.03, 1), (1.01, 0), (0.97, 1), (1.0, 0)])
async def test_prompt_eval_count_against_the_local_count(factor: float, overflow: int) -> None:
    seen: list[str] = []
    counter = spy_counter(seen)
    messages = build_prompt("Frist?", _hits()[:1], CFG)
    local = count_prompt_tokens(messages, counter, CFG)
    respx.post(URL).mock(return_value=_reply(round(local * factor)))
    stats = Stats()
    gen = OllamaChatGenerator(CFG, "http://llm-proxy:11500", stats=stats, count_tokens=counter)
    await gen.answer("Frist?", _hits()[:1])
    assert stats.prompt_overflow == overflow
    assert any("<|im_start|>system" in t for t in seen)  # counted with the injected tokenizer


@respx.mock
async def test_prompt_eval_count_at_the_budget_counts_as_overflow_even_without_a_tokenizer() -> (
    None
):
    respx.post(URL).mock(return_value=_reply(8192 - 256))
    stats = Stats()
    await OllamaChatGenerator(CFG, "http://llm-proxy:11500", stats=stats).answer(
        "Frist?", _hits()[:1]
    )
    assert stats.prompt_overflow == 1


def test_fit_hits_cuts_a_prefix_when_the_count_exceeds_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [hit(cid, rank) for rank, cid in enumerate(IDS, start=1)]
    monkeypatch.setattr(budget_mod, "prompt_budget", lambda _cfg: 1500)
    kept = fit_hits("Q?", hits, CFG, len)  # one character per token
    assert 1 <= len(kept) < len(hits)
    assert kept == hits[: len(kept)]
    assert count_prompt_tokens(build_prompt("Q?", kept, CFG), len, CFG) <= 1500 or len(kept) == 1


@respx.mock
async def test_the_generator_reports_only_the_chunks_that_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(URL).mock(return_value=_reply(100))
    monkeypatch.setattr(budget_mod, "prompt_budget", lambda _cfg: 1500)
    gen = OllamaChatGenerator(CFG, "http://llm-proxy:11500", stats=Stats(), count_tokens=len)
    out = await gen.answer("Q?", _hits())
    assert 1 <= len(out.prompt_chunk_ids) < len(IDS)
    assert out.prompt_chunk_ids == IDS[: len(out.prompt_chunk_ids)]
    sent = json.loads(respx.calls.last.request.content)["messages"][1]["content"]
    assert IDS[-1] not in sent


def test_build_generator_loads_the_generator_tokenizer_never_the_embedding_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[Path] = []

    def fake_loader(path: Path) -> Callable[[str], int]:
        loaded.append(path)
        return len

    monkeypatch.setattr(wiring, "load_token_counter", fake_loader)
    settings = Settings(generator_tokenizer=Path("gen.json"), embed_tokenizer=Path("bge.json"))
    wiring.build_generator(
        CFG, "http://llm-proxy:11500", Stats(), tokenizer=settings.generator_tokenizer
    )
    assert loaded == [Path("gen.json")]


def test_the_generator_tokenizer_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_GENERATOR_TOKENIZER", "/app/tokenizers/generator.json")
    assert Settings().generator_tokenizer == Path("/app/tokenizers/generator.json")


def test_the_request_timeout_comes_from_the_catalogue_entry_else_300_seconds() -> None:
    catalogue = load_catalogue(CATALOGUE)
    default = wiring.build_generator(CFG, "http://llm-proxy:11500", Stats(), catalogue=catalogue)
    assert default.timeout_s == 300.0  # type: ignore[attr-defined]  # Generator protocol
    entry = catalogue["ollama/qwen3.8:27b-q8_0"].model_copy(update={"request_timeout_s": 123.0})
    slower = wiring.build_generator(
        CFG, "http://llm-proxy:11500", Stats(), catalogue={entry.id: entry}
    )
    assert slower.timeout_s == 123.0  # type: ignore[attr-defined]  # Generator protocol
