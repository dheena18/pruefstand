"""Citation metrics: precision / recall / F1 vs ``gold_citations`` and ``citation_grounded``."""

from functools import lru_cache
from typing import Literal

from pruefstand.core.citations import (
    Citation,
    citation_credit,
    extract_citations,
    normalise,
    parse_one,
)
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.base import BaseMetric

MAX_CITATION_CHARS = (
    20_000  # per text; cost cap against huge answers (reported as details["truncated"])
)
MAX_CHUNK_CHARS_TOTAL = 100_000


@lru_cache(maxsize=4)
def _predict(answer: str, citations: tuple[str, ...]) -> tuple[tuple[Citation, ...], bool]:
    """Citations of one response, extracted once (the four metrics share the result)."""
    truncated = len(answer) > MAX_CITATION_CHARS
    budget = MAX_CITATION_CHARS
    texts = []
    for text in citations:
        part = text[:budget]
        truncated |= len(part) < len(text)
        budget -= len(part)
        texts.append(part)
    texts.append(answer[:MAX_CITATION_CHARS])
    seen: dict[str, Citation] = {}
    for text in texts:
        for citation in extract_citations(text):
            seen.setdefault(normalise(citation), citation)
    return tuple(seen.values()), truncated


@lru_cache(maxsize=4)
def _chunk_citations(texts: tuple[str, ...]) -> tuple[frozenset[str], bool]:
    """Normalised citations occurring in the chunk texts (capped per text and in total)."""
    truncated = False
    budget = MAX_CHUNK_CHARS_TOTAL
    known: set[str] = set()
    for text in texts:
        part = text[: min(MAX_CITATION_CHARS, budget)]
        truncated |= len(part) < len(text)
        budget -= len(part)
        known.update(normalise(c) for c in extract_citations(part))
    return frozenset(known), truncated


def predicted_citations(resp: TargetResponse) -> list[Citation]:
    """Citations the target stated: ``resp.citations`` plus those found in the answer.

    Deduplicated by the default-granularity normalised form, in first-seen order. Only the first
    20 000 characters are read (``MAX_CITATION_CHARS``), a defence against huge answers.

    Examples:
        >>> from pruefstand.core.models.target import TargetResponse
        >>> resp = TargetResponse(answer="Nach § 622 Absatz 2 BGB", citations=("§ 622 Abs. 2 BGB",))
        >>> [normalise(c) for c in predicted_citations(resp)]
        ['§ 622 Abs. 2 BGB']
    """
    return list(_predict(resp.answer, resp.citations)[0])


def _truncation(*, truncated: bool) -> dict[str, bool]:
    return {"truncated": True} if truncated else {}


def f1_score(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall; 0 when both are 0.

    Examples:
        >>> round(f1_score(0.5, 1.0), 3)
        0.667
        >>> f1_score(0.0, 0.0)
        0.0
    """
    total = precision + recall
    return 0.0 if total == 0.0 else 2 * precision * recall / total


class _CitationScore(BaseMetric):
    """Precision, recall or F1 with the 1 / 0.5 / 0 credit of ``citation_credit`` (AI9-17)."""

    higher_is_better = True
    version = "2"  # D890: the law alias table gained ZPO, VwGO, SGG, EStG
    component: Literal["precision", "recall", "f1"]

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        if not case.gold_citations:
            return self.na("no_gold_citations")
        gold = [parse_one(text) for text in case.gold_citations]
        parsed = [g for g in gold if g is not None]
        if len(parsed) != len(gold):
            return self.error("unparseable_gold_citation")
        pred_tuple, truncated = _predict(resp.answer, resp.citations)
        pred = list(pred_tuple)
        recall = sum(max((citation_credit(p, g) for p in pred), default=0.0) for g in parsed)
        recall /= len(parsed)
        precision = sum(max(citation_credit(p, g) for g in parsed) for p in pred)
        precision = precision / len(pred) if pred else 0.0
        scores = {"precision": precision, "recall": recall, "f1": f1_score(precision, recall)}
        return self.ok(scores[self.component], **_truncation(truncated=truncated))


class CitationPrecision(_CitationScore):
    """Mean over predicted citations of the best credit against the gold set."""

    name = "citation_precision"
    component = "precision"


class CitationRecall(_CitationScore):
    """Mean over gold citations of the best credit among the predictions (the gated one)."""

    name = "citation_recall"
    component = "recall"


class CitationF1(_CitationScore):
    """Harmonic mean of citation precision and recall."""

    name = "citation_f1"
    component = "f1"


class CitationGrounded(BaseMetric):
    """Share of predicted citations that occur in a retrieved chunk's text (R9 X3.2).

    A prediction is grounded when its normalised form equals the normalised form of a citation
    extracted from some chunk text. The API v1 ``RetrievedChunk`` carries no ``citation_key``,
    so the text is the only evidence available here. Catches hallucinated norms.
    """

    name = "citation_grounded"
    version = "2"  # D890: see _CitationScore
    higher_is_better = True
    requires = frozenset({"chunks"})

    def _compute(self, _case: TestCase, resp: TargetResponse) -> MetricValue:
        pred, answer_truncated = _predict(resp.answer, resp.citations)
        if not pred:
            return self.na("no_predicted_citation")
        known, chunks_truncated = _chunk_citations(tuple(chunk.text for chunk in resp.chunks or ()))
        share = sum(normalise(p) in known for p in pred) / len(pred)
        return self.ok(share, **_truncation(truncated=answer_truncated or chunks_truncated))
