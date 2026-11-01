"""``DecisionSectionChunker``: court decisions split at their headings (T2.3).

A heading is a **whole line** (case-insensitive, an optional ``I.``/``A.``/``2.`` enumerator and a
trailing colon allowed, letter-spaced ``T a t b e s t a n d :`` read as one word) found in the
decision text; the line itself is not part of the chunk, the name goes to ``Chunk.section``:

* ``Tenor``; ``Tatbestand``; ``Entscheidungsgründe`` (also ``Gründe``, ``Aus den Gründen``);
  ``Leitsatz`` (also ``Leitsätze``, ``Orientierungssatz``, the juris name of the same thing).
* ``Verfahrensgang``, ``Streitwertbeschluss`` and ``Rechtsmittelbelehrung`` end the running section
  and start text with ``section=None``; text before the first heading is ``section=None`` too.
* ``Hinweis``, ``Fußnoten``, ``Anmerkung``, ``Diese Entscheidung zitiert`` and the other apparatus
  headings of the juris export end the decision: everything after them is dropped.
* A bare ``I.``/``II.`` is *not* a section boundary (it stays inside the running section).

A decision without any of the four named sections is cut into 512-token windows with 64 tokens of
overlap (:func:`~pruefstand.ingest.chunkers.fixed.token_windows`) and ``section=None``.

A section of at most ``max_tokens`` tokens (approximate, see ``fixed.py``) is one chunk. A
longer one is split at **Randnummern** (a line holding only a number that grows by 1 to 10 against
the previous one; a list that restarts at 1 is not a Randnummer) or, when there are fewer than two,
at its lines. The units are packed greedily into chunks of at most ``max_tokens`` tokens, never cut
apart, so a chunk starts at a Randnummer; one unit longer than ``max_tokens`` is cut into
overlapping windows. All chunks of a section keep its name; ids are ``<doc_id>#0``, ``#1``,
... over the whole decision.

Every step is one pass over the lines (a line longer than 48 characters is never tested as a
heading), so the time is linear in the text.
"""

import re
from dataclasses import dataclass
from itertools import pairwise

from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.chunkers.fixed import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_OVERLAP,
    build_chunk,
    check_window,
    token_windows,
)
from pruefstand.ingest.text import count_tokens

_MAX_HEADING_CHARS = 48
_ENUMERATOR = re.compile(r"(?:[IVX]{1,5}|[A-E]|\d{1,2})\.\s+")
_NAMED = {
    "tenor": "Tenor",
    "tatbestand": "Tatbestand",
    "entscheidungsgründe": "Entscheidungsgründe",
    "gründe": "Entscheidungsgründe",
    "aus den gründen": "Entscheidungsgründe",
    "leitsatz": "Leitsatz",
    "leitsätze": "Leitsatz",
    "amtlicher leitsatz": "Leitsatz",
    "orientierungssatz": "Leitsatz",
    "orientierungssätze": "Leitsatz",
}
_UNNAMED = frozenset({"verfahrensgang", "streitwertbeschluss", "rechtsmittelbelehrung"})
_TRAILER = frozenset(
    {
        "hinweis", "fußnoten", "anmerkung", "diese entscheidung zitiert",
        "diese entscheidung wird zitiert", "weitere fundstellen", "weitere fundstellen ...",
        "sonstige literatur",
    }
)  # fmt: skip
_MAX_RN_GAP = 10
_MAX_RN_DIGITS = 4


@dataclass(frozen=True)
class Segment:
    """Consecutive non-blank lines under one heading (``section=None``: no named heading)."""

    section: str | None
    lines: list[str]


def _heading_key(line: str) -> str:
    """Return the casefolded heading candidate of ``line`` (``""`` if it cannot be a heading)."""
    text = line.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return ""
    text = text.lstrip("#").strip()
    found = _ENUMERATOR.match(text)
    if found:
        text = text[found.end() :]
    text = text.rstrip(" :").casefold()
    words = text.split()
    if len(words) >= 3 and all(len(word) == 1 for word in words):
        return "".join(words)  # "t a t b e s t a n d"
    return text


def split_sections(text: str) -> list[Segment]:
    r"""Split a decision text at its heading lines.

    Args:
        text: Decision text, one paragraph per line (the OLDP loader's output).

    Returns:
        The segments in document order; heading lines are not included, empty segments and
        everything after an apparatus heading (``Fußnoten``, ...) are dropped.

    Examples:
        >>> [(s.section, s.lines) for s in split_sections("Tenor\nAbgewiesen.\nGründe\nKeine.")]
        [('Tenor', ['Abgewiesen.']), ('Entscheidungsgründe', ['Keine.'])]
    """
    segments: list[Segment] = []
    section: str | None = None
    lines: list[str] = []
    for raw in text.split("\n"):
        key = _heading_key(raw)
        if key in _TRAILER:
            break
        if key in _NAMED or key in _UNNAMED:
            if lines:
                segments.append(Segment(section, lines))
            section, lines = _NAMED.get(key), []
        elif raw.strip():
            lines.append(raw.strip())
    if lines:
        segments.append(Segment(section, lines))
    return segments


def has_named_sections(text: str) -> bool:
    """Return whether ``text`` has a Tenor, Tatbestand, Entscheidungsgründe or Leitsatz heading."""
    return any(segment.section is not None for segment in split_sections(text))


def _randnummer(line: str, last: int | None) -> int | None:
    if not (line.isascii() and line.isdigit()) or len(line) > _MAX_RN_DIGITS:
        return None
    number = int(line)
    return number if last is None or last < number <= last + _MAX_RN_GAP else None


def _units(lines: list[str]) -> list[str]:
    """Group ``lines`` into Randnummer blocks (or single lines when fewer than two numbers)."""
    last: int | None = None
    starts: list[int] = []
    for index, line in enumerate(lines):
        number = _randnummer(line, last)
        if number is not None:
            starts.append(index)
            last = number
    if len(starts) < 2:
        return lines
    bounds = [0, *starts] if starts[0] > 0 else starts
    edges = [*bounds, len(lines)]
    return ["\n".join(lines[a:b]) for a, b in pairwise(edges)]


def _pack(lines: list[str], max_tokens: int, overlap: int) -> list[str]:
    """Pack the units of ``lines`` into pieces of at most ``max_tokens`` tokens."""
    pieces: list[str] = []
    buffer: list[str] = []
    size = 0
    for unit in _units(lines):
        tokens = count_tokens(unit)
        if (tokens > max_tokens or size + tokens > max_tokens) and buffer:
            pieces.append("\n".join(buffer))
            buffer, size = [], 0
        if tokens > max_tokens:
            pieces.extend(token_windows(unit, max_tokens, overlap))
        else:
            buffer.append(unit)
            size += tokens
    if buffer:
        pieces.append("\n".join(buffer))
    return pieces


class DecisionSectionChunker:
    """Chunker for court decisions (see the module docstring for the rules).

    Args:
        max_tokens: Largest chunk in approximate tokens (default 512).
        overlap: Overlap of the windows of the fallback and of oversized units (default 64).

    Raises:
        ValueError: Invalid ``max_tokens`` / ``overlap``.
    """

    def __init__(
        self, max_tokens: int = DEFAULT_MAX_TOKENS, overlap: int = DEFAULT_OVERLAP
    ) -> None:
        check_window(max_tokens, overlap)
        self.max_tokens = max_tokens
        self.overlap = overlap

    def chunk(self, doc: Document) -> list[Chunk]:
        """Split ``doc`` into section chunks (or fixed windows when it has no section).

        Args:
            doc: A decision as produced by :class:`~pruefstand.ingest.oldp.OldpLoader`.

        Returns:
            The chunks in order; empty when the text has no content.
        """
        segments = split_sections(doc.text)
        pieces: list[tuple[str | None, str]]
        if not any(segment.section for segment in segments):
            joined = "\n".join(line for segment in segments for line in segment.lines)
            pieces = [
                (None, window) for window in token_windows(joined, self.max_tokens, self.overlap)
            ]
        else:
            pieces = [
                (segment.section, piece) for segment in segments for piece in self._split(segment)
            ]
        return [build_chunk(doc, i, section, text) for i, (section, text) in enumerate(pieces)]

    def _split(self, segment: Segment) -> list[str]:
        text = "\n".join(segment.lines)
        if count_tokens(text) <= self.max_tokens:
            return [text]
        return _pack(segment.lines, self.max_tokens, self.overlap)
