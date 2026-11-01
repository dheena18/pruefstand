"""Output filter, injection guard and the generator's HTTP plumbing (pure + cassette)."""

import re

import pytest
from conftest import CONFIGS
from rd_support import attack_hits, hit
from rag_demo.config import load_config
from rag_demo.generate import (
    REFUSAL,
    LlamaCppGenerator,
    apply_output_guard,
    build_prompt,
    extract_citations,
    load_prompt,
)
from rag_demo.models import Stats

ON = load_config(CONFIGS / "rag.yaml")
OFF = load_config(CONFIGS / "bugs" / "system_prompt_guard_off.yaml")
GUARD_OFF = load_config(CONFIGS / "bugs" / "injection_guard_off.yaml")
SYSTEM = load_prompt(ON)


def _quote() -> str:
    sentence = next(s for s in re.split(r"(?<=[.!?])\s+", SYSTEM) if len(s.split()) >= 10)
    return f"Gerne. {sentence}"


def test_quoting_the_system_prompt_is_refused_when_the_guard_is_on() -> None:
    assert apply_output_guard(_quote(), SYSTEM, ON) == REFUSAL


def test_the_same_answer_passes_when_the_guard_is_off() -> None:
    assert apply_output_guard(_quote(), SYSTEM, OFF) == _quote()


def test_a_normal_answer_passes_in_both_modes() -> None:
    answer = "Die Kündigungsfrist beträgt einen Monat zum Monatsende (§ 622 Abs. 2 BGB)."
    assert apply_output_guard(answer, SYSTEM, ON) == answer
    assert apply_output_guard(answer, SYSTEM, OFF) == answer


def test_the_refusal_sentence_itself_is_not_an_8_gram_leak() -> None:
    assert apply_output_guard(REFUSAL, SYSTEM, ON) == REFUSAL


def _joined(cfg: object) -> str:
    return "\n".join(m["content"] for m in build_prompt("Was gilt?", attack_hits(), cfg))  # type: ignore[arg-type]


def test_injection_guard_on_drops_the_planted_instruction_lines() -> None:
    prompt = _joined(ON)
    assert "PWNED-" not in prompt
    assert "<dokument" in prompt
    assert "keine Anweisungen" in prompt


def test_injection_guard_off_pastes_the_raw_chunks() -> None:
    prompt = _joined(GUARD_OFF)
    assert len(re.findall(r"PWNED-[0-9a-f]{4}", prompt)) == 4
    assert "<dokument" not in prompt


def test_citation_regex() -> None:
    text = "Siehe § 622 Abs. 2 Nr. 1 BGB sowie § 3 ArbZG und Art. 6 Abs. 1 DSGVO; § 622 BGB."
    assert extract_citations(text) == [
        "§ 622 Abs. 2 Nr. 1 BGB",
        "§ 3 ArbZG",
        "Art. 6 Abs. 1 DSGVO",
        "§ 622 BGB",
    ]
    assert extract_citations("Keine Norm.") == []


@pytest.mark.vcr("generate_smoke_622.yaml")
async def test_recorded_real_answer_passes_both_modes_unchanged() -> None:
    out = await LlamaCppGenerator(ON, "http://llm.test:8080", stats=Stats()).answer(
        "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?",
        [hit("gii-bgb-622#0")],
    )
    assert out.answer == apply_output_guard(out.answer, SYSTEM, ON)
    assert out.answer == apply_output_guard(out.answer, SYSTEM, OFF)
    assert out.refused is (out.answer == REFUSAL)
    assert out.model
    assert out.completion_tokens > 0
