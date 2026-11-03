"""Deterministic checks of the QA filters on candidates and their sources (T4.3).

``check_evidence``: the citation must name a source chunk and the evidence must lie in the cited
Absatz of a chunk the citation names (T4.2 left both to this filter). ``drop_cluster_overlap``:
the second document of a pair must not be the cluster of another case (leakage between splits).
``style_report``: the layperson share of the kept set (report level, nothing is dropped for it).
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from pruefstand.core.citations import extract_citations
from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import FilterResult, QACandidate
from pruefstand.dataset.evidence import cited_absatz, cites_chunk, evidence_span
from pruefstand.dataset.to_case import case_id_of


def sources_of(c: QACandidate, chunks: Mapping[ChunkId, Chunk]) -> list[Chunk] | None:
    """The chunks of a candidate (gold chunk first), or None when one is not in ``chunks``."""
    ids = (c.chunk_id, *c.extra_chunk_ids)
    if any(i not in chunks for i in ids):
        return None
    return [chunks[i] for i in ids]


def check_evidence(c: QACandidate, sources: Sequence[Chunk]) -> FilterResult:
    r"""Check citation and evidence against the chunks the citation names.

    A citation that parses but names none of the source paragraphs is ``citation_mismatch``. An
    ``evidence_span`` must be a span of the cited Absatz of a chunk the citation names; the whole
    chunk is accepted only when the citation names the paragraph without an Absatz, or the chunk
    has no Absätze (``evidence_off_paragraph``). A missing citation or evidence is not a reason:
    they are reported by the caller.

    Args:
        c: The candidate.
        sources: Its chunks (gold chunk first).

    Returns:
        The verdict.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> kw = dict(doc_id="d", tenant="t", lang="de", section=None, parallel_id=None,
        ...           version_date=None, license="l", source="gii:bgb", citation_key="§ 622 BGB")
        >>> chunk = Chunk(chunk_id="a#0", text="(1) Eins gilt.\n(2) Zwei gilt.", **kw)
        >>> cand = QACandidate(question="q?", answer="a", citation="§ 622 Abs. 1 BGB",
        ...                    chunk_id="a#0", prompt_version="qa_factual_de_v1",
        ...                    evidence_span="Zwei gilt.")
        >>> check_evidence(cand, [chunk]).reasons
        ('evidence_off_paragraph',)
    """
    named = bool(extract_citations(c.citation or ""))
    cited = [s for s in sources if cites_chunk(c.citation, s)]
    if named and not cited:
        return FilterResult(kept=False, reasons=("citation_mismatch",))
    if c.evidence_span is not None and not any(
        evidence_span(c.evidence_span, s.text, cited_absatz(c.citation, s)) is not None
        for s in cited
    ):
        return FilterResult(kept=False, reasons=("evidence_off_paragraph",))
    return FilterResult(kept=True, reasons=())


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
