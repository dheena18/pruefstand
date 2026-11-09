"""The ``evidence_span`` rule of QA generation (round 9 AI9-06, X3.2; interfaces §2).

The model must copy the answer-bearing sentence(s) of the cited Absatz verbatim. The span is kept
only when, after whitespace and soft-hyphen normalisation, it is a substring of the source chunk,
lies inside the cited Absatz and has at most 60 tokens; otherwise it is dropped (never repaired).
Tokens are counted as words and single punctuation marks, which is a conservative stand-in for
the model tokenizer (it counts at least as many tokens as a word piece tokenizer for German text
of this length would count words).
"""

import re

from pruefstand.core.citations import extract_citations, parse_one
from pruefstand.core.models.corpus import Chunk

MAX_EVIDENCE_TOKENS = 60
_SOFT_HYPHEN = "­"
_TOKEN = re.compile(r"\w+|[^\w\s]")
_MARKER = re.compile(r"(?<!\w)\((\d+[a-z]?)\)\s")


def normalise_text(text: str) -> str:
    r"""Remove soft hyphens and collapse every whitespace run to one space.

    Examples:
        >>> normalise_text("Kün\u00addigung  nach\n§ 622")
        'Kündigung nach § 622'
    """
    return " ".join(text.replace(_SOFT_HYPHEN, "").split())


def count_tokens(text: str) -> int:
    """Count words and punctuation marks.

    Examples:
        >>> count_tokens("Ein Monat, bitte.")
        5
    """
    return len(_TOKEN.findall(text))


def _scope(body: str, absatz: str | None) -> str | None:
    """Return the part of ``body`` that may hold the evidence (None: the Absatz is not there)."""
    if absatz is None:
        return body
    markers = list(_MARKER.finditer(body))
    if not markers:
        return body  # a paragraph without Absätze
    for number, marker in enumerate(markers):
        if marker.group(1) == absatz:
            end = markers[number + 1].start() if number + 1 < len(markers) else len(body)
            return body[marker.start() : end]
    preamble = body[: markers[0].start()]  # a chunk may continue an Absatz of the previous chunk
    return preamble if preamble.strip() else None


def evidence_span(evidence: str, text: str, absatz: str | None) -> str | None:
    r"""Return the normalised ``evidence`` if it is a valid span of ``text``, else None.

    Args:
        evidence: The model's ``evidence`` string.
        text: The source chunk's text.
        absatz: The Absatz named by the citation (``"2"``), or None when it names none.

    Returns:
        The normalised span, or None when it is empty, longer than 60 tokens, not a substring of
        the chunk, or outside the cited Absatz.

    Examples:
        >>> chunk = "(2) Die Frist beträgt einen Monat.\n(3) In der Probezeit zwei Wochen."
        >>> evidence_span("Die Frist beträgt   einen Monat.", chunk, "2")
        'Die Frist beträgt einen Monat.'
        >>> evidence_span("In der Probezeit zwei Wochen.", chunk, "2") is None
        True
    """
    span = normalise_text(evidence)
    if not span or count_tokens(span) > MAX_EVIDENCE_TOKENS:
        return None
    scope = _scope(normalise_text(text), absatz)
    return span if scope is not None and span in scope else None


def cited_absatz(citation: str | None, chunk: Chunk) -> str | None:
    """Return the Absatz that ``citation`` names for the paragraph of ``chunk``.

    Args:
        citation: The model's citation (possibly several, separated by ``;`` or ``und``).
        chunk: The chunk whose ``citation_key`` selects the matching citation.

    Returns:
        The Absatz number, or None when the citation names none for this chunk's paragraph.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> c = Chunk(
        ...     chunk_id="a#0", doc_id="a", tenant="t", lang="de", text="x",
        ...     citation_key="§ 622 BGB", section=None, parallel_id=None, version_date=None,
        ...     license="l", source="gii:bgb",
        ... )
        >>> cited_absatz("§ 1 Abs. 3 KSchG und § 622 Abs. 2 BGB", c)
        '2'
    """
    if not citation:
        return None
    found = extract_citations(citation)
    key = parse_one(chunk.citation_key) if chunk.citation_key else None
    if key is None:
        return found[0].absatz if len(found) == 1 else None
    for item in found:
        if (item.kind, item.number, item.law) == (key.kind, key.number, key.law):
            return item.absatz
    return None


def cites_chunk(citation: str | None, chunk: Chunk) -> bool:
    """Return False when ``citation`` names other paragraphs only and none of this chunk's.

    A missing or unparsable citation (or a chunk without ``citation_key``) cannot say so: True.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> c = Chunk(
        ...     chunk_id="a#0", doc_id="a", tenant="t", lang="de", text="x",
        ...     citation_key="§ 622 BGB", section=None, parallel_id=None, version_date=None,
        ...     license="l", source="gii:bgb",
        ... )
        >>> cites_chunk("§ 1 KSchG", c), cites_chunk("§ 622 Abs. 2 BGB", c)
        (False, True)
    """
    found = extract_citations(citation or "")
    key = parse_one(chunk.citation_key) if chunk.citation_key else None
    if not found or key is None:
        return True
    return any((f.kind, f.number, f.law) == (key.kind, key.number, key.law) for f in found)


def absatz_scope(body: str, absatz: str | None) -> str | None:
    """Return the text of Absatz ``absatz`` in the normalised ``body`` (all of it if it has none).

    None means the chunk does not hold that Absatz. T4.7a uses it to limit the fact check of a
    reference answer to the Absatz its citation names.
    """
    return _scope(body, absatz)
