"""Candidate -> ``TestCase`` (T4.2): cluster, licence config, normalised gold citations.

The conversion happens after filtering (T4.3) in the build orchestration (T4.7a); this module
only holds the pure rules. ``split`` is provisional: ``assign_splits`` (T4.1) sets the real one.
"""

import hashlib
from collections.abc import Sequence

from pruefstand.core.citations import extract_citations, normalise
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import CaseId, DocId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.testcase import TestCase

_LICENSE_OF_SOURCE = {
    "gii": "laws_eurlex",
    "eurlex": "laws_eurlex",
    "oldp": "oldp_derived",
    "germanquad": "germanquad_derived",
    "germanrag": "germanrag_derived",
}
_DIFFICULTY = {
    Category.FACTUAL: Difficulty.EASY,
    Category.COMPARISON: Difficulty.MEDIUM,
    Category.CROSS_LINGUAL: Difficulty.MEDIUM,
    Category.MULTI_HOP: Difficulty.HARD,
}


def license_config_of(chunks: Sequence[Chunk]) -> str | None:
    """Return the one licence config a case over ``chunks`` can have, or None.

    Laws are § 5 UrhG public-domain works, so a law plus a decision is ``oldp_derived``. Two
    different share-alike configs (``oldp_derived``, ``germanquad_derived``, ``germanrag_derived``)
    never mix: None means "drop the pair" (also for a source with no config).

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> kw = dict(doc_id="d", tenant="t", lang="de", text="x", citation_key=None, section=None,
        ...           parallel_id=None, version_date=None, license="l")
        >>> law = Chunk(chunk_id="a", source="gii:bgb", **kw)
        >>> decision = Chunk(chunk_id="b", source="oldp:decisions", **kw)
        >>> license_config_of([law, decision])
        'oldp_derived'
    """
    configs = {_LICENSE_OF_SOURCE.get(c.source.split(":", 1)[0]) for c in chunks}
    if None in configs or not configs:
        return None
    share_alike = configs - {"laws_eurlex"}
    if len(share_alike) > 1:
        return None
    return next(iter(share_alike)) if share_alike else "laws_eurlex"


def _gold_citations(c: QACandidate, chunk: Chunk) -> tuple[str, ...]:
    found = [normalise(item) for item in extract_citations(c.citation or "")]
    unique = tuple(dict.fromkeys(found))
    if unique:
        return unique
    return (chunk.citation_key,) if chunk.citation_key else ()


def _cluster_doc(category: Category, chunk: Chunk, extra: Chunk | None) -> DocId:
    if category is Category.CROSS_LINGUAL and extra is not None:
        return next((x.doc_id for x in (chunk, extra) if x.lang is Lang.DE), chunk.doc_id)
    return chunk.doc_id


def case_id_of(c: QACandidate) -> CaseId:
    """Return the stable id of a candidate: a hash of prompt, chunks and question (T4.3 order)."""
    text = "|".join([c.prompt_version, c.chunk_id, *c.extra_chunk_ids, c.question])
    return CaseId("qa-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])


def to_test_case(
    c: QACandidate,
    chunk: Chunk,
    category: Category,
    *,
    corpus_version: str,
    split: Split = Split.FULL,
    difficulty: Difficulty | None = None,
    extra_chunk: Chunk | None = None,
) -> TestCase:
    """Convert a filtered candidate into an unperturbed ``TestCase``.

    Args:
        c: The candidate.
        chunk: Its source chunk (``c.chunk_id``; the gold chunk of a pair).
        category: The case category.
        corpus_version: Version of the corpus the chunks come from.
        split: Provisional split (``assign_splits`` replaces it).
        difficulty: Default by category (factual easy, comparison and cross-lingual medium,
            multi-hop hard).
        extra_chunk: The second chunk of a multi-hop or cross-lingual pair.

    Returns:
        The case with ``base_id == id``, ``cluster_id`` = the source document (the German
        document of a cross-lingual pair), ``source="generated"``, normalised ``gold_citations``
        and the ``evidence_span`` of the candidate.

    Raises:
        DatasetError: The chunks have no single licence config (see ``license_config_of``).
    """
    chunks = [chunk] if extra_chunk is None else [chunk, extra_chunk]
    licence = license_config_of(chunks)
    if licence is None:
        msg = f"{c.chunk_id}: no single licence config for sources {[x.source for x in chunks]}"
        raise DatasetError(msg)
    both = category is Category.MULTI_HOP and extra_chunk is not None
    case_id = case_id_of(c)
    return TestCase(
        id=case_id,
        base_id=case_id,
        cluster_id=_cluster_doc(category, chunk, extra_chunk),
        tenant=chunk.tenant,
        lang=c.lang,
        question=c.question,
        reference_answer=c.answer,
        gold_doc_ids=tuple(x.doc_id for x in chunks) if both else (chunk.doc_id,),
        gold_citations=_gold_citations(c, chunk),
        evidence_span=c.evidence_span,
        category=category,
        difficulty=difficulty or _DIFFICULTY[category],
        split=split,
        source="generated",
        license_config=licence,
        generation_prompt_version=c.prompt_version,
        corpus_version=corpus_version,
    )
