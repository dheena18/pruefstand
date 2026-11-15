"""Sentence answers for the ``correctness`` ``negate`` discrimination cell (T5.4b).

Most ``correctness`` positives are short annotator spans (names, numbers, dates) without a finite
verb, so ``rq2.construct.negate`` changes only 21 of the 197 ``test`` positives (D932). This module
lifts a positive to its GermanQuAD source sentence and negates that sentence instead: the base
answer is the context sentence that contains the positive span, the degraded answer is the same
sentence with ``negate`` applied. Deterministic, no model (D1240).

A sentence is used only when it is a single, complete sentence (T5.4b2: no merged or cut
sentences) and clean after removing wiki italics (``clean_span``: no other
markup, balanced brackets), the span starts in its first clause, the negation is not after the
span and ``negation_ok`` holds, so the negation lands on the clause that carries the answer.
"""

from collections.abc import Sequence

from rq2.calib_schema import CalibrationItem
from rq2.calib_sources import QuadRow
from rq2.construct import clean_span, negate, split_sentences
from rq2.construct_checks import first_clause_end, is_single_sentence, negation_ok

WIKI_ITALICS = "''"
"""Wiki italics, removed from sentence and span (``Ground Zero`` instead of ``''Ground Zero''``)."""


def _span(answer: str) -> str:
    return answer.replace(WIKI_ITALICS, "").strip().rstrip(".").strip()


def answer_sentence(row: QuadRow, answer: str) -> str | None:
    """Return the first clean context sentence of ``row`` that contains ``answer``.

    Args:
        row: The GermanQuAD question (its paragraph is searched).
        answer: The positive answer span (a trailing full stop is ignored).

    Returns:
        The sentence without wiki italics, or ``None`` when no clean sentence contains the span.
    """
    span = _span(answer)
    if not span:
        return None
    sentences = (s.replace(WIKI_ITALICS, "") for s in split_sentences(row.context))
    return next(
        (s for s in sentences if span in s and clean_span(s) and is_single_sentence(s)), None
    )


def negated_sentence(row: QuadRow, answer: str) -> tuple[str, str] | None:
    """Return ``(sentence, negated sentence)`` for one positive, or ``None``.

    ``None`` when there is no clean sentence, the span starts after the first clause, ``negate``
    finds no negation or listed verb, the edit comes after the end of the span (then it
    negates another part, e.g. "Im Vergleich zu anderen Schwermetallen ist nicht Kupfer ..."), or
    ``negation_ok`` rejects the edit.
    """
    sentence = answer_sentence(row, answer)
    if sentence is None:
        return None
    span = _span(answer)
    start = sentence.find(span)
    edited = negate(sentence)
    if start >= first_clause_end(sentence) or edited is None or edited == sentence:
        return None
    if _first_diff(sentence, edited) > start + len(span) or not negation_ok(sentence, edited):
        return None
    return sentence, edited


def _first_diff(a: str, b: str) -> int:
    pairs = enumerate(zip(a, b, strict=False))
    return next((i for i, (x, y) in pairs if x != y), min(len(a), len(b)))


def match_row(item: CalibrationItem, rows: Sequence[QuadRow]) -> QuadRow | None:
    """Return the one GermanQuAD row of ``item`` (same question, reference and article)."""
    hits = [
        r
        for r in rows
        if r.question == item.inputs["frage"]
        and r.answers
        and r.answers[0][0] == item.inputs["referenz"]
        and "germanquad:" + r.article == item.cluster_id
    ]
    return hits[0] if len(hits) == 1 else None
