"""Deterministic checks of the QA filters on candidates and their sources (T4.3).

``check_evidence``: the citation must name a source chunk and the evidence must lie in the cited
Absatz of a chunk the citation names (T4.2 left both to this filter). ``drop_cluster_overlap``:
the second document of a pair must not be the cluster of another case (leakage between splits).
``style_report``: the layperson share of the kept set (report level, nothing is dropped for it).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from pruefstand.core.citations import extract_citations
from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import FilterResult, QACandidate
from pruefstand.dataset.evidence import (
    MAX_EVIDENCE_TOKENS,
    cited_absatz,
    cites_chunk,
    count_tokens,
    normalise_text,
)
from pruefstand.dataset.to_case import case_id_of


def sources_of(c: QACandidate, chunks: Mapping[ChunkId, Chunk]) -> list[Chunk] | None:
    """The chunks of a candidate (gold chunk first), or None when one is not in ``chunks``."""
    ids = (c.chunk_id, *c.extra_chunk_ids)
    if any(i not in chunks for i in ids):
        return None
    return [chunks[i] for i in ids]


_MARKER = re.compile(r"(?<!\w)\((\d+[a-z]?)\)\s")
_ABSATZ = re.compile(
    r"(?i:Absatz|Abs\.?)\s*\(?\s*\d+[a-z]?\)?(?:\s*(?:,|und|bis|[–—-])\s*\(?\d+[a-z]?\)?)*"
)
_NUMBER = re.compile(r"\d+[a-z]?")
_RANGE = re.compile(r"bis|[–—-]")
MIN_EVIDENCE_WORDS = 3
_MAX_RANGE = 30


def absaetze_of(citation: str) -> list[str]:
    """All Absatz numbers a citation names, ranges expanded (``Abs. 1 bis 3`` -> 1, 2, 3).

    Examples:
        >>> absaetze_of("Art. 5 Abs. 1 bis 3 DSGVO")
        ['1', '2', '3']
        >>> absaetze_of("§ 622 Abs. 2 und 3 BGB")
        ['2', '3']
    """
    found: list[str] = []
    for match in _ABSATZ.finditer(citation):
        numbers = _NUMBER.findall(match.group(0))
        first, last = numbers[0], numbers[-1]
        spans = _RANGE.search(match.group(0)) and first.isdigit() and last.isdigit()
        if spans and 0 <= int(last) - int(first) <= _MAX_RANGE:
            numbers = [str(n) for n in range(int(first), int(last) + 1)]
        found += numbers
    return found


def _lead(number: str) -> int:
    return int("".join(ch for ch in number if ch.isdigit()))


def _scope(source: Chunk, absaetze: set[str] | None) -> str | None:
    """The text of ``source`` in which evidence for the cited Absätze may lie (None: nowhere)."""
    body = unicodedata.normalize("NFC", normalise_text(source.text))
    if absaetze is None:
        return body
    later = int(source.chunk_id.rsplit("#", 1)[-1] or 0) > 0
    markers = list(_MARKER.finditer(body))
    if not markers:  # no Absätze: a lone Absatz 1, or the continuation of a long Absatz
        return body if later or absaetze <= {"1"} else None
    parts = [
        body[m.start() : markers[n + 1].start() if n + 1 < len(markers) else len(body)]
        for n, m in enumerate(markers)
        if m.group(1) in absaetze
    ]
    first = _lead(markers[0].group(1))
    # the text before the first marker is a continuation only in a later chunk, and only of an
    # Absatz that comes before that marker; in the first chunk it is the heading (never evidence)
    if not parts and later and all(a[:1].isdigit() and _lead(a) < first for a in absaetze):
        parts.append(body[: markers[0].start()])
    return " ".join(parts) if parts else None


def _cited_absaetze(c: QACandidate, source: Chunk) -> set[str] | None:
    first = cited_absatz(c.citation, source)
    if first is None:
        return None
    if len(extract_citations(c.citation or "")) == 1:
        return {first, *absaetze_of(c.citation or "")}
    return {first}


def _evidence_reason(c: QACandidate, cited: Sequence[Chunk]) -> str | None:
    span = unicodedata.normalize("NFC", normalise_text(c.evidence_span or ""))
    if len(span.split()) < MIN_EVIDENCE_WORDS:
        return "evidence_too_short"
    if count_tokens(span) > MAX_EVIDENCE_TOKENS:
        return "evidence_off_paragraph"
    anywhere = False
    for source in cited:
        scope = _scope(source, _cited_absaetze(c, source))
        if scope is not None and span in scope:
            return None
        anywhere = anywhere or span in unicodedata.normalize("NFC", normalise_text(source.text))
    return "evidence_not_in_cited_absatz" if anywhere else "evidence_off_paragraph"


def check_evidence(c: QACandidate, sources: Sequence[Chunk]) -> FilterResult:
    r"""Check citation and evidence against the chunks the citation names.

    Reasons: ``citation_missing``, ``citation_unparsed``, ``citation_mismatch`` (it parses but
    names none of the source paragraphs), ``evidence_missing``, ``evidence_too_short`` (fewer than
    3 words), ``evidence_not_in_cited_absatz`` (the text is in a cited chunk but outside the cited
    Absatz or range; an Absatz the chunk does not have is accepted only for the text before the
    first Absatz marker of a LATER chunk, never for the heading of the first chunk) and
    ``evidence_off_paragraph`` (in no cited chunk, or over 60 tokens). A citation without Absatz
    accepts the whole cited chunk.

    Args:
        c: The candidate.
        sources: Its chunks (gold chunk first).

    Returns:
        The verdict; several reasons can apply.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> kw = dict(doc_id="d", tenant="t", lang="de", section=None, parallel_id=None,
        ...           version_date=None, license="l", source="gii:bgb", citation_key="§ 622 BGB")
        >>> chunk = Chunk(chunk_id="a#0", text="(1) Eins gilt hier.\n(2) Zwei gilt hier.", **kw)
        >>> cand = QACandidate(question="q?", answer="a", citation="§ 622 Abs. 1 BGB",
        ...                    chunk_id="a#0", prompt_version="qa_factual_de_v1",
        ...                    evidence_span="Zwei gilt hier.")
        >>> check_evidence(cand, [chunk]).reasons
        ('evidence_not_in_cited_absatz',)
    """
    reasons: list[str] = []
    cited = list(sources)
    if not c.citation:
        reasons.append("citation_missing")
    elif not extract_citations(c.citation):
        reasons.append("citation_unparsed")
    else:
        cited = [s for s in sources if cites_chunk(c.citation, s)]
        if not cited:
            return FilterResult(kept=False, reasons=("citation_mismatch",))
    if c.evidence_span is None:
        reasons.append("evidence_missing")
    elif (reason := _evidence_reason(c, cited)) is not None:
        reasons.append(reason)
    return FilterResult(kept=not reasons, reasons=tuple(reasons))


def doc_group(chunk: Chunk) -> str:
    """The document group of a chunk: its ``parallel_id`` (DE and EN of one norm), else its doc."""
    return chunk.parallel_id or chunk.doc_id


def _cluster_group(c: QACandidate, sources: Sequence[Chunk]) -> str:
    """Group of the cluster document (``to_test_case``): the German one of a cross-lingual pair."""
    first = sources[0]
    if c.extra_chunk_ids and c.prompt_version.startswith("qa_cross_lingual"):
        first = next((s for s in sources if s.lang is Lang.DE), first)
    return doc_group(first)


def drop_cluster_overlap(
    cands: Sequence[QACandidate], chunks: Mapping[ChunkId, Chunk]
) -> tuple[list[QACandidate], list[QACandidate]]:
    """Split ``cands`` into kept and dropped so no pair uses another case's cluster document.

    The cluster of a case is its source document (``to_test_case``). A pair (multi-hop or
    cross-lingual) also shows its second document; when that document is the cluster of another
    case, the two cases would leak into different splits, so the pair is dropped. Single-chunk
    candidates are never dropped. Pairs are decided greedily in the order of their stable ids, so
    the result does not depend on the input order. A candidate whose chunks are missing is kept
    (``check_evidence`` / the caller report it).

    Returns:
        ``(kept, dropped)``, both in the input order.
    """
    info = {case_id_of(c): (c, sources_of(c, chunks)) for c in cands}
    clusters: Counter[str] = Counter()
    for c, sources in info.values():
        if sources is not None and not c.extra_chunk_ids:
            clusters[_cluster_group(c, sources)] += 1
    foreign: set[str] = set()
    dropped: set[str] = set()
    for key in sorted(info):
        c, sources = info[key]
        if sources is None or not c.extra_chunk_ids:
            continue
        own = _cluster_group(c, sources)
        others = {doc_group(s) for s in sources} - {own}
        if others & set(clusters) or own in foreign:
            dropped.add(key)
            continue
        clusters[own] += 1
        foreign |= others
    return (
        [c for c in cands if case_id_of(c) not in dropped],
        [c for c in cands if case_id_of(c) in dropped],
    )


class StyleReport(BaseModel):
    """Layperson share of a candidate set; ``ok`` is None below the minimum count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    laie: int
    fachlich: int
    unknown: int
    share: float | None
    minimum: float
    ok: bool | None


def style_report(cands: Sequence[QACandidate], minimum: float, min_n: int) -> StyleReport:
    """Count the styles and check the layperson share (prompt v1 asks for at least 60 %).

    The share is laie / (laie + fachlich); candidates with no style are counted ``unknown`` and
    stay out of it. The check is evaluated only from ``min_n`` styled candidates on (a handful of
    cases says nothing about a share).

    Examples:
        >>> from pruefstand.core.models.dataset import QACandidate
        >>> def cand(s):
        ...     return QACandidate(question="q?", answer="a", citation=None, chunk_id="a#0",
        ...                        prompt_version="qa_factual_de_v1", style=s)
        >>> r = style_report([cand("laie")] * 3 + [cand("fachlich")] * 2, 0.6, 5)
        >>> (r.share, r.ok)
        (0.6, True)
        >>> style_report([cand("laie")], 0.6, 5).ok is None
        True
    """
    laie = sum(1 for c in cands if c.style == "laie")
    fachlich = sum(1 for c in cands if c.style == "fachlich")
    styled = laie + fachlich
    share = laie / styled if styled else None
    ok = None if share is None or styled < min_n else share >= minimum
    return StyleReport(
        laie=laie,
        fachlich=fachlich,
        unknown=len(cands) - styled,
        share=share,
        minimum=minimum,
        ok=ok,
    )
