"""Where may the evidence of a QA candidate lie? Absatz scopes of a chunk (T4.3, D829).

A chunk holds one or more Absätze. German chunks mark them ``(1) ``, English EUR-Lex chunks
``1. `` at the start of a line. The text before the first marker is the heading of a first chunk
(``#0``, never evidence) or the continuation of the last Absatz of the previous chunk (a later
chunk). A cited Absatz that exists nowhere is never accepted, and neither is Absatz 0.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence

from pruefstand.core.citations import extract_citations
from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.dataset.evidence import cites_chunk, normalise_text

_PAREN = r"(?<!\w)\((\d+[a-z]?)\)\s"
_MARKER_DE = re.compile(_PAREN)
_MARKER_EN = re.compile(rf"(?m){_PAREN}|^(\d+[a-z]?)\.\s")
_ABSATZ = re.compile(
    r"(?i:Absatz|Abs\.?)\s*\(?\s*\d+[a-z]?\)?(?:\s*(?:,|und|bis|[–—-])\s*\(?\d+[a-z]?\)?)*"
)
_NUMBER = re.compile(r"\d+[a-z]?")
_RANGE = re.compile(r"bis|[–—-]")
_SPLIT = re.compile(r"\s*;\s*|\s+(?:und|sowie)\s+(?=§|Art)|\s+(?:i\.\s?V\.\s?m\.|iVm)\s+")
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


def lead_int(number: str) -> int:
    """The numeric part of an Absatz number (``2a`` -> 2)."""
    return int("".join(ch for ch in number if ch.isdigit()))


def cited_absaetze(citation: str | None, source: Chunk) -> set[str] | None:
    """The Absätze the citation names for the norm of ``source`` (None: the whole norm).

    A citation of several norms (``;``, ``und § ...``) is split, so a range applies to its own
    norm only.
    """
    if not citation:
        return None
    named = [
        seg for seg in _SPLIT.split(citation) if extract_citations(seg) and cites_chunk(seg, source)
    ]
    found = {a for seg in named for a in absaetze_of(seg)}
    return found or None


def _markers(raw: str, lang: Lang) -> list[tuple[int, str]]:
    pattern = _MARKER_EN if lang is Lang.EN else _MARKER_DE
    return [(m.start(), m.group(1) or m.group(2)) for m in pattern.finditer(raw)]


def _index(chunk: Chunk) -> int:
    tail = chunk.chunk_id.rsplit("#", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _last_absatz(source: Chunk, chunks: Mapping[ChunkId, Chunk]) -> str | None:
    """The Absatz in which the previous chunk(s) of the same document end (None: unknown)."""
    doc = source.chunk_id.rsplit("#", 1)[0]
    for j in range(_index(source) - 1, -1, -1):
        prev = chunks.get(ChunkId(f"{doc}#{j}"))
        if prev is None:
            return None
        marks = _markers(unicodedata.normalize("NFC", prev.text), prev.lang)
        if marks:
            return marks[-1][1]
        if j == 0:
            return "1"
    return None


def _norm(text: str) -> str:
    return normalise_text(unicodedata.normalize("NFC", text))


def scopes(
    source: Chunk, absaetze: set[str] | None, chunks: Mapping[ChunkId, Chunk]
) -> list[str] | None:
    """The normalised texts in which evidence for the cited Absätze may lie, None: nowhere.

    Adjacent cited Absätze form one text, so evidence may span ``Abs. 1 und 2``. ``absaetze``
    None (a citation without Absatz) accepts the whole chunk except the heading of a first chunk.
    """
    raw = unicodedata.normalize("NFC", source.text)
    marks = _markers(raw, source.lang)
    later = _index(source) > 0
    if absaetze is None:
        return [_norm(raw[marks[0][0] :] if marks and not later else raw)]
    if any(lead_int(a) == 0 for a in absaetze):
        return None
    if not marks:  # a lone Absatz 1, or the continuation of a long Absatz
        if later:
            last = _last_absatz(source, chunks)
            return [_norm(raw)] if last is not None and last in absaetze else None
        return [_norm(raw)] if absaetze <= {"1"} else None
    ends = [m[0] for m in marks[1:]] + [len(raw)]
    pieces = [(n, num, raw[s:e]) for n, ((s, num), e) in enumerate(zip(marks, ends, strict=True))]
    chosen = [(n, text) for n, num, text in pieces if num in absaetze]
    if later and raw[: marks[0][0]].strip():
        last = _last_absatz(source, chunks)
        if last in absaetze and lead_int(last) < lead_int(marks[0][1]):
            chosen.insert(0, (-1, raw[: marks[0][0]]))
    runs: list[list[tuple[int, str]]] = []
    for item in chosen:
        if runs and runs[-1][-1][0] == item[0] - 1:
            runs[-1].append(item)
        else:
            runs.append([item])
    return [_norm("".join(t for _, t in run)) for run in runs] or None


def contains_words(scope: str, span: str) -> bool:
    """True when ``span`` occurs in ``scope`` on word boundaries (no partial words)."""
    return re.search(rf"(?<!\w){re.escape(span)}(?!\w)", scope) is not None


def content_words(span: str) -> int:
    """Number of words of ``span`` without Absatz markers (``(3)``, a leading ``2.``)."""
    plain = re.sub(r"\(\d+[a-z]?\)", " ", span)
    plain = re.sub(r"^\s*\d+[a-z]?\.\s", "", plain)
    return len(plain.split())


def whole_text(chunks: Sequence[Chunk]) -> list[str]:
    """The normalised full texts of ``chunks``."""
    return [_norm(c.text) for c in chunks]
