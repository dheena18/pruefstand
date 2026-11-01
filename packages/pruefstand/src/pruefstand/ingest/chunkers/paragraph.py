"""``ParagraphChunker``: one chunk per § or Artikel, long ones split by Absatz (T2.2).

A document is one § (or Artikel), so it normally becomes exactly one chunk. When its text has
more than ``max_tokens`` tokens (:func:`pruefstand.ingest.text.count_tokens`; default 2 000) and
at least two Absätze, **every** Absatz becomes its own chunk with ``section="Abs. N"``, the same
``citation_key`` and ids ``<doc_id>#0``, ``#1``, ... A single Absatz is never cut, so one longer
than the limit stays whole (the limit is a split trigger, not a hard cap).

An Absatz starts at a line ``(N)`` or ``(Na)``. Numbers must grow (``1, 1a, 2, 3``): a list inside
an Absatz that restarts at ``(1)`` is not a new Absatz. Text before the first marker belongs to
the first Absatz. An Absatz that is only ``(N) (weggefallen)`` is folded into the previous
(or, at the start, the next) chunk instead of becoming a chunk of its own. The chunks together
hold exactly the document text (up to whitespace).

The scan is one pass over the lines and the token count one regex pass, so the time is linear.
"""

import re

from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.text import count_tokens

DEFAULT_MAX_TOKENS = 2000
_MARKER = re.compile(r"\((\d{1,3})([a-z]{0,2})\)(?!\w)")
_REPEALED_ABSATZ = re.compile(r"\(\d{1,3}[a-z]{0,2}\)\s*\(weggefallen\)\Z")


def _marker(line: str, last: tuple[int, str] | None) -> tuple[int, str] | None:
    """Return ``(number, suffix)`` of an Absatz marker at the start of ``line`` if it follows."""
    found = _MARKER.match(line.lstrip())
    if found is None:
        return None
    current = (int(found.group(1)), found.group(2))
    return current if last is None or current > last else None


def split_absaetze(text: str) -> list[tuple[str, str]]:
    r"""Split ``text`` at Absatz markers into ``(label, text)`` pairs (``"Abs. 2"``, ``"..."``).

    Args:
        text: A § as produced by the GII loader (one paragraph per line).

    Returns:
        One pair per Absatz in order; an empty list when the text has no marker.

    Examples:
        >>> split_absaetze("(1) Eins.\n(2) Zwei.\n1. Liste")
        [('Abs. 1', '(1) Eins.'), ('Abs. 2', '(2) Zwei.\n1. Liste')]
    """
    labels: list[str] = []
    parts: list[list[str]] = []
    preamble: list[str] = []
    last: tuple[int, str] | None = None
    for line in text.split("\n"):
        marker = _marker(line, last)
        if marker is not None:
            last = marker
            labels.append(f"Abs. {marker[0]}{marker[1]}")
            parts.append([line])
        elif parts:
            parts[-1].append(line)
        else:
            preamble.append(line)
    if parts:
        parts[0] = [*preamble, *parts[0]]
    pairs = [(label, "\n".join(lines).strip()) for label, lines in zip(labels, parts, strict=True)]
    return _merge_repealed(pairs)


def _merge_repealed(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold ``(N) (weggefallen)`` Absätze into a neighbour: they are not worth a chunk."""
    merged: list[tuple[str, str]] = []
    carry: list[str] = []
    for label, body in pairs:
        if _REPEALED_ABSATZ.match(body):
            if merged:
                merged[-1] = (merged[-1][0], f"{merged[-1][1]}\n{body}")
            else:
                carry.append(body)
        else:
            merged.append((label, "\n".join([*carry, body])))
            carry = []
    return merged


class ParagraphChunker:
    """Chunker for statutes: one chunk per § / Artikel, split by Absatz when too long.

    Args:
        max_tokens: Split trigger in tokens (see the module docstring); must be positive.

    Raises:
        ValueError: ``max_tokens`` is not positive.
    """

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        if max_tokens < 1:
            msg = "max_tokens must be positive"
            raise ValueError(msg)
        self.max_tokens = max_tokens

    def chunk(self, doc: Document) -> list[Chunk]:
        """Split ``doc`` into chunks.

        ``citation_key`` and a nested ``section`` (``"§ 1"`` of an EGBGB Artikel) are read from
        ``doc.metadata``; a split chunk's section is ``"Abs. N"`` or ``"§ 1 Abs. N"``.

        Args:
            doc: A document whose text holds one § or Artikel.

        Returns:
            The chunks in order; empty when the text is blank.
        """
        text = doc.text.strip()
        if not text:
            return []
        base = doc.metadata.get("section")
        parts: list[tuple[str | None, str]] = [(None, text)]
        if count_tokens(text) > self.max_tokens:
            absaetze = split_absaetze(text)
            if len(absaetze) > 1:
                parts = list(absaetze)
        return [
            self._make(doc, index, " ".join(filter(None, (base, label))) or None, body)
            for index, (label, body) in enumerate(parts)
        ]

    @staticmethod
    def _make(doc: Document, index: int, section: str | None, text: str) -> Chunk:
        return Chunk(
            chunk_id=ChunkId(f"{doc.doc_id}#{index}"),
            doc_id=doc.doc_id,
            tenant=doc.tenant,
            lang=doc.lang,
            text=text,
            citation_key=doc.metadata.get("citation_key"),
            section=section,
            parallel_id=None,
            version_date=doc.version_date,
            license=doc.license,
            source=doc.source,
        )
