"""``evidence_recall``, the RQ1 span-level retrieval metric (X3.2, D122, D162; interfaces §5).

An **experiment metric** owned by T7.3: it lives here, is in neither ``KNOWN_METRICS`` nor the
``MetricRegistry`` and is never gated. Per case it is 1 if any retrieved chunk's text contains the
case's gold ``TestCase.evidence_span`` after normalisation, 0 otherwise, and ``not_applicable``
when the case has no span. Both sides are normalised the same way (:func:`normalise_span`), so a
chunk that breaks a word at a line end or uses a non-breaking space still contains the span.
"""

import re
import unicodedata
from collections.abc import Sequence

from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.target import RetrievedChunk
from pruefstand.core.models.testcase import TestCase

METRIC = "evidence_recall"
METRIC_VERSION = "1"
_SOFT_HYPHEN = "­"
# A hyphen at a line end before a lower-case letter is a word broken by hyphenation
# ("Kündi-" newline "gungsfrist"): the hyphen goes. Before an upper-case letter it is the hyphen
# of a compound ("EU-" newline "Recht"): only the line break goes.
_BROKEN_WORD = re.compile(r"(\w)-[^\S\n]*\n\s*(?=[^\W\d_])")


def _join_line_hyphen(match: re.Match[str]) -> str:
    rest = match.string[match.end()]
    return match.group(1) if rest.islower() else match.group(1) + "-"


def normalise_span(text: str) -> str:
    r"""Normalise a span or a chunk text for the containment test.

    NFC; soft hyphens removed; a word broken by a line-end hyphen joined; every whitespace run
    (non-breaking spaces included) collapsed to one space; the ends stripped.

    Args:
        text: span or chunk text.

    Returns:
        The normalised text.

    Examples:
        >>> normalise_span("Die Kündi-\ngungsfrist  beträgt\tvier Wochen. ")
        'Die Kündigungsfrist beträgt vier Wochen.'
        >>> normalise_span("nach EU-\nRecht")
        'nach EU-Recht'
    """
    text = unicodedata.normalize("NFC", text).replace(_SOFT_HYPHEN, "")
    text = _BROKEN_WORD.sub(_join_line_hyphen, text)
    return " ".join(text.split())


def evidence_recall(case: TestCase, chunks: Sequence[RetrievedChunk]) -> MetricValue:
    r"""Score whether the retrieved chunks contain the case's gold evidence span.

    A span split across two chunks is in neither chunk and scores 0: the metric asks whether the
    answer-bearing text was retrieved in one piece.

    Args:
        case: the test case; its ``evidence_span`` is the gold span (None: no span was emitted).
        chunks: the chunks the target retrieved for this case, in any order.

    Returns:
        ``ok`` with 1.0 or 0.0, or ``not_applicable`` (reason ``no_evidence_span``) when the
        case has no span.

    Examples:
        >>> from pruefstand.core.enums import Category, Difficulty, Lang, Split
        >>> case = TestCase(
        ...     id="c1", base_id="c1", cluster_id="k1", tenant="shared_public", lang=Lang.DE,
        ...     question="Wie lang ist die Kündigungsfrist?", reference_answer="Vier Wochen.",
        ...     evidence_span="Die Kündigungsfrist beträgt vier Wochen.",
        ...     category=Category.FACTUAL, difficulty=Difficulty.EASY, split=Split.RQ1,
        ...     source="doctest", license_config="doctest", corpus_version="v1",
        ... )
        >>> text = "(1) Die Kündi-\ngungsfrist beträgt vier Wochen."
        >>> hit = RetrievedChunk(chunk_id="b#0", doc_id="b", text=text, score=0.9, rank=1)
        >>> evidence_recall(case, [hit]).value
        1.0
        >>> evidence_recall(case, []).value
        0.0
    """
    if case.evidence_span is None:
        return MetricValue(
            metric=METRIC,
            metric_version=METRIC_VERSION,
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            details={"reason": "no_evidence_span"},
        )
    span = normalise_span(case.evidence_span)
    hit = any(span in normalise_span(chunk.text) for chunk in chunks)
    return MetricValue(
        metric=METRIC,
        metric_version=METRIC_VERSION,
        value=1.0 if hit else 0.0,
        status=MetricStatus.OK,
    )
