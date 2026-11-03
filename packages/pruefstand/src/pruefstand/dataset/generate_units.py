"""Units of QA generation: prompt specs, one unit per request, and candidate construction.

A *unit* is what one datagen request is about: one chunk (factual, comparison) or two (multi-hop,
cross-lingual). Units are built from the caller's generator in input order, with the same draws
for every unit, so the request seeds and styles of a resumed run equal those of the first run.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from pruefstand.core.citations import extract_citations
from pruefstand.core.enums import Category, Lang
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.dataset.evidence import cited_absatz, cites_chunk, evidence_span
from pruefstand.llm.prompts import PromptRegistry

PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"
LAIE_SHARE = 0.7  # prompt v1 asks for >= 60 % layperson questions; the draw has margin
MAX_TOKENS = 700
_NAME = re.compile(r"^(qa_(factual|multi_hop|comparison|cross_lingual)_de)_(v[0-9]+)$")
_CATEGORY = {
    "factual": Category.FACTUAL,
    "multi_hop": Category.MULTI_HOP,
    "comparison": Category.COMPARISON,
    "cross_lingual": Category.CROSS_LINGUAL,
}
_LANGUAGE_NAME = {Lang.DE: "Deutsch", Lang.EN: "Englisch"}


class QAAnswer(BaseModel):
    """The JSON object the datagen model returns (validated with ``complete_json``)."""

    model_config = ConfigDict(extra="ignore")

    question: str = Field(min_length=3)
    answer: str = Field(min_length=1)
    citation: str | None = None
    evidence: str = ""
    style: str | None = None


@dataclass(frozen=True)
class PromptSpec:
    """A parsed ``prompt_version`` such as ``qa_factual_de_v1``."""

    prompt_id: str
    version: str
    category: Category

    @property
    def name(self) -> str:
        """The ``prompt_version`` string stored on candidates."""
        return f"{self.prompt_id}_{self.version}"

    @property
    def is_pair(self) -> bool:
        """True for the two-chunk prompts (multi-hop, cross-lingual)."""
        return self.category in {Category.MULTI_HOP, Category.CROSS_LINGUAL}


def parse_prompt_version(prompt_version: str) -> PromptSpec:
    """Split ``qa_factual_de_v1`` into prompt id, version and category.

    Raises:
        ConfigError: The name is not one of the four QA prompt families.

    Examples:
        >>> parse_prompt_version("qa_multi_hop_de_v1").category.value
        'multi_hop'
    """
    match = _NAME.match(prompt_version)
    if match is None:
        msg = f"unknown QA prompt '{prompt_version}' (expected qa_<kind>_de_v<N>)"
        raise ConfigError(msg)
    return PromptSpec(match.group(1), match.group(3), _CATEGORY[match.group(2)])


@dataclass(frozen=True)
class Unit:
    """One request: its chunks (the gold chunk first), seed, style, question language and key."""

    chunks: tuple[Chunk, ...]
    seed: int
    style: str
    lang: Lang
    key: str


def unit_key(spec: PromptSpec, model: str, chunks: Sequence[Chunk]) -> str:
    """Return the resume key of a unit: prompt, model and chunk ids (gold chunk first)."""
    return f"{spec.name}|{model}|{'+'.join(c.chunk_id for c in chunks)}"


def build_units(
    spec: PromptSpec, model: str, groups: Sequence[Sequence[Chunk]], rng: np.random.Generator
) -> list[Unit]:
    """Build one unit per chunk or pair; every unit consumes the same three draws of ``rng``.

    A cross-lingual pair is ``(German chunk, English chunk)`` in either order; the draw decides the
    direction: an English question is answered from the German chunk and the other way round.
    """
    units: list[Unit] = []
    for group in groups:
        seed = int(rng.integers(0, 2**31 - 1))
        style = "laie" if rng.random() < LAIE_SHARE else "fachlich"
        english = rng.random() < 0.5
        chunks, lang = tuple(group), Lang.DE
        if spec.category is Category.CROSS_LINGUAL:
            german = next((c for c in group if c.lang is Lang.DE), group[0])
            other = next(c for c in group if c is not german)
            chunks, lang = ((german, other), Lang.EN) if english else ((other, german), Lang.DE)
        units.append(Unit(chunks, seed, style, lang, unit_key(spec, model, chunks)))
    return units


def unit_for_candidate(c: QACandidate, chunks: dict[str, Chunk], model: str, seed: int) -> Unit:
    """Rebuild the unit of an existing candidate (cross-check): same chunks, language and style."""
    spec = parse_prompt_version(c.prompt_version)
    group = tuple(chunks[i] for i in (c.chunk_id, *c.extra_chunk_ids))
    return Unit(group, seed, c.style or "laie", c.lang, unit_key(spec, model, group))


def _variables(spec: PromptSpec, unit: Unit) -> dict[str, str]:
    first = unit.chunks[0]
    quelle = first.citation_key or "unbekannt"
    if spec.category is Category.MULTI_HOP:
        second = unit.chunks[1]
        return {
            "stil": unit.style,
            "quelle_a": quelle,
            "text_a": first.text,
            "quelle_b": second.citation_key or "unbekannt",
            "text_b": second.text,
        }
    if spec.category is Category.CROSS_LINGUAL:
        return {
            "stil": unit.style,
            "frage_sprache": _LANGUAGE_NAME[unit.lang],
            "quelle": quelle,
            "text_gold": first.text,
            "text_andere": unit.chunks[1].text,
        }
    return {"stil": unit.style, "quelle": quelle, "text": first.text}


def build_request(spec: PromptSpec, unit: Unit, model: str, registry: PromptRegistry) -> LLMRequest:
    """Render the prompt of ``unit`` into a datagen request (temperature 0, cacheable)."""
    template = registry.get(spec.prompt_id, spec.version)
    return LLMRequest(
        role=LLMRole.DATAGEN,
        model=model,
        messages=template.render(**_variables(spec, unit)),
        temperature=0.0,
        max_tokens=MAX_TOKENS,
        seed=unit.seed,
        prompt_id=spec.prompt_id,
        prompt_version=spec.version,
        response_format="json",
    )


def _span(spec: PromptSpec, answer: QAAnswer, unit: Unit) -> str | None:
    """Check the evidence against the gold chunk (cross-lingual) or either chunk (multi-hop)."""
    sources = unit.chunks[:1] if spec.category is Category.CROSS_LINGUAL else unit.chunks
    for chunk in sources:
        if not cites_chunk(answer.citation, chunk):
            continue
        span = evidence_span(answer.evidence, chunk.text, cited_absatz(answer.citation, chunk))
        if span is not None:
            return span
    return None


def _style(value: str | None) -> Literal["laie", "fachlich"] | None:
    if value == "laie":
        return "laie"
    return "fachlich" if value == "fachlich" else None


def make_candidate(spec: PromptSpec, unit: Unit, answer: QAAnswer) -> tuple[QACandidate, list[str]]:
    """Build the candidate of an answer; also return the counter names to increase.

    Returns:
        ``(candidate, notes)`` where notes may hold ``evidence_invalid`` (the evidence is not a
        valid span, so ``evidence_span`` is None) and ``citation_unparsed``.
    """
    notes: list[str] = []
    span = _span(spec, answer, unit)
    if span is None:
        notes.append("evidence_invalid")
    if answer.citation and not extract_citations(answer.citation):
        notes.append("citation_unparsed")
    cand = QACandidate(
        question=answer.question.strip(),
        answer=answer.answer.strip(),
        citation=answer.citation.strip() if answer.citation else None,
        chunk_id=unit.chunks[0].chunk_id,
        prompt_version=spec.name,
        evidence_span=span,
        extra_chunk_ids=tuple(c.chunk_id for c in unit.chunks[1:]),
        lang=unit.lang,
        style=_style(answer.style),
    )
    return cand, notes
