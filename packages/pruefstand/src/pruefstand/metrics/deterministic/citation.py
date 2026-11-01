"""Citation metrics: precision / recall / F1 vs ``gold_citations`` and ``citation_grounded``."""

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


def predicted_citations(resp: TargetResponse) -> list[Citation]:
    """Citations the target stated: ``resp.citations`` plus those found in the answer.

    Deduplicated by the default-granularity normalised form, in first-seen order.

    Examples:
        >>> from pruefstand.core.models.target import TargetResponse
        >>> resp = TargetResponse(answer="Nach § 622 Absatz 2 BGB", citations=("§ 622 Abs. 2 BGB",))
        >>> [normalise(c) for c in predicted_citations(resp)]
        ['§ 622 Abs. 2 BGB']
    """
    seen: dict[str, Citation] = {}
    for text in (*resp.citations, resp.answer):
        for citation in extract_citations(text):
            seen.setdefault(normalise(citation), citation)
    return list(seen.values())


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
    component: Literal["precision", "recall", "f1"]

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        if not case.gold_citations:
            return self.na("no_gold_citations")
        gold = [parse_one(text) for text in case.gold_citations]
        parsed = [g for g in gold if g is not None]
        if len(parsed) != len(gold):
            return self.error("unparseable_gold_citation")
        pred = predicted_citations(resp)
        recall = sum(max((citation_credit(p, g) for p in pred), default=0.0) for g in parsed)
        recall /= len(parsed)
        precision = sum(max(citation_credit(p, g) for g in parsed) for p in pred)
        precision = precision / len(pred) if pred else 0.0
        scores = {"precision": precision, "recall": recall, "f1": f1_score(precision, recall)}
        return self.ok(scores[self.component])


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
    higher_is_better = True
    requires = frozenset({"chunks"})

    def _compute(self, _case: TestCase, resp: TargetResponse) -> MetricValue:
        pred = predicted_citations(resp)
        if not pred:
            return self.na("no_predicted_citation")
        known = {normalise(c) for chunk in resp.chunks or () for c in extract_citations(chunk.text)}
        return self.ok(sum(normalise(p) in known for p in pred) / len(pred))
