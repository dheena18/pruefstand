"""Find German and EU legal citations in free text (T1.5a).

A scan over *heads* (``§``, ``Art.``, ``Section`` ...): each head is followed by a number list,
optional qualifiers (Abs., S., Nr., lit., ``(2)``, ``ff.``, skipped UAbs./Hs./Alt./Var.) and a law
name from the alias table. A head takes at most one of each qualifier, so a head never rescans
text another head already consumed (linear time). A citation without a resolvable law is dropped
and logged at debug level.

Conventions: number lists (``622, 623``, ``17 und 18``, ranges) expand to one citation each for
every head; qualifiers after a list belong to its last number; several qualifier values
(``Abs. 2, 3``, ``lit. a und b``) keep the first. A law-less citation borrows the law of the next
one when both heads are of the same kind and joined by ``i.V.m.``, ``und``, ``sowie`` or ``,``.
A number may carry a suffix of one or two lowercase letters (``5a``, ``53ca``); ``ff``/``f.``
("folgende") and function words such as ``in`` or ``im`` never are one.
``§`` (kind ``para``) exists only for national laws: ``§ 6 DSGVO`` is dropped.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pruefstand.core.citations.aliases import is_national, match_law
from pruefstand.core.citations.model import Citation
from pruefstand.core.logging import get_logger

_log = get_logger(__name__)
Kind = Literal["para", "art"]

_WORD_END = r"(?![A-Za-zÄÖÜäöüß])"
# Two-letter German function words never read as a suffix (`Art. 6in`, `§ 6im`), nor does `ff`
# ("folgende"). Three or more letters are never a suffix (the word-end lookahead).
_NOT_SUFFIX = r"(?!ff|(?:am|an|da|du|er|es|im|in|ja|je|ob|so|um|wo|zu)" + _WORD_END + r")"
_NUM = (
    r"[0-9]{1,5}(?![0-9])"
    rf"(?:(?!ff?\.)(?:{_NOT_SUFFIX}[a-z]{{2}}|[a-z]){_WORD_END})?"
)
_LET = rf"[a-z]{_WORD_END}"
_NUM_AT = re.compile(rf"\s*({_NUM})")
_HEAD = re.compile(
    r"(?:§§?|(?<![\w.])s\.|(?<!\w)(?i:Paragraph|Paragraf|Sections?|Secs?\.|Artikel|Articles?"
    r"|Artt\.|Arts\.|Art\.))(?=\s*[0-9])"
)
_ENGLISH_HEADS = {"s.", "section", "sections", "sec.", "secs."}
_RANGE = re.compile(rf"\s*(?:bis|[–—-])\s*(?P<end>{_NUM})")
_LIST_SEP = re.compile(r"\s*(?:,|&|und|and|sowie)(?=\s*[0-9])")
_LINK = re.compile(r"\s*(?:i\.\s?V\.\s?m\.|iVm|in\s+Verbindung\s+mit)\s*")
_AND = re.compile(r"\s*(?:,|&|und|and|sowie)\s*")
_MAX_RANGE = 50
_MIN_CAP = 100
_CAP_DIVISOR = 20  # at most one citation per 20 characters of input (floor: 100)
_FIELDS = ("absatz", "satz", "nummer", "lit")


def _values(name: str) -> str:
    """Regex for one or more values (``2``, ``2, 3``, ``2 bis 4``); the group keeps the first."""
    return rf"(?P<{name}>{_NUM})(?:\s*(?:,|und|bis|[–—-])\s*{_NUM})*"


_QUALIFIER = re.compile(
    r"[\s,]*(?:"
    + "|".join(
        [
            r"(?i:Absatz|Abs\.?)\s*\(?\s*" + _values("absatz") + r"\s*\)?",
            r"(?:(?i:Satz)|S\.|s\.)\s*" + _values("satz"),
            r"(?i:Nummer|Nr\.)\s*" + _values("nummer"),
            r"(?i:lit\.|Buchstabe|Buchst\.|Bst\.)\s*\(?\s*(?P<lit>" + _LET + r")"
            rf"(?:\s*(?:,|und|sowie|bis|[–—-])\s*{_LET})*\s*\)?",
            r"(?i:UAbs\.|Unterabs\.|Unterabsatz|Halbsatz|Hs\.|Alt\.|Alternative|Var\.|Variante)"
            r"\s*" + _values("skip"),
            rf"\(\s*(?:(?P<p_num>{_NUM})|(?P<p_lit>[a-z]))\s*\)",
            r"(?P<ff>ff?\.)(?!\w)",
        ]
    )
    + ")"
)


@dataclass(frozen=True)
class _Draft:
    """A citation whose law is not known yet."""

    kind: Kind
    number: str
    absatz: str | None = None
    satz: str | None = None
    nummer: str | None = None
    lit: str | None = None

    def with_law(self, law: str) -> Citation:
        return Citation(
            kind=self.kind,
            number=self.number,
            absatz=self.absatz,
            satz=self.satz,
            nummer=self.nummer,
            lit=self.lit,
            law=law,
        )


@dataclass(frozen=True)
class _Parsed:
    """Result of one head: drafts (empty = nothing to keep), the law if present, end offset."""

    drafts: list[_Draft]
    law: str | None
    end: int


def _expand(first: str, last: str) -> list[str]:
    """Expand ``first..last`` when both are plain numbers and the span is small."""
    if first.isdigit() and last.isdigit() and 0 <= int(last) - int(first) < _MAX_RANGE:
        return [str(n) for n in range(int(first), int(last) + 1)]
    return [first, last]


def _numbers(text: str, pos: int) -> tuple[list[str], int] | None:
    """Read a number list (with ranges) after a head."""
    numbers: list[str] = []
    while (m := _NUM_AT.match(text, pos)) is not None:
        pos = m.end()
        rng = _RANGE.match(text, pos)
        if rng is not None:
            numbers += _expand(m.group(1), rng.group("end"))
            pos = rng.end()
        else:
            numbers.append(m.group(1))
        sep = _LIST_SEP.match(text, pos)
        if sep is None:
            break
        pos = sep.end()
    return (numbers, pos) if numbers else None


def _apply(m: re.Match[str], fields: dict[str, str]) -> bool:
    """Record one qualifier; False when its field is already set (a head takes each once)."""
    name, value = next(
        ((n, m.group(n)) for n in _FIELDS if m.group(n) is not None),
        ("absatz", m.group("p_num")) if m.group("p_num") is not None else ("lit", m.group("p_lit")),
    )
    if value is None:
        return True  # ff. / f. and the skipped UAbs./Hs./Alt./Var.: dropped
    if name in fields:
        return False
    fields[name] = value
    return True


def _qualifiers(text: str, pos: int) -> tuple[dict[str, str], int]:
    fields: dict[str, str] = {}
    while (m := _QUALIFIER.match(text, pos)) is not None and _apply(m, fields):
        pos = m.end()
    return fields, pos


def _classify(head: str) -> tuple[Kind, bool]:
    folded = head.casefold()
    kind: Kind = "art" if folded.startswith("art") else "para"
    return kind, folded in _ENGLISH_HEADS


def _drop(reason: str, start: int) -> None:
    """Log a dropped citation at debug level (reason and offset only, never the text)."""
    if _log.isEnabledFor(logging.DEBUG):
        _log.debug("citation_dropped", reason=reason, offset=start)


def _parse_at(text: str, head: re.Match[str]) -> _Parsed | None:
    kind, english = _classify(head.group())
    read = _numbers(text, head.end())
    if read is None:
        _drop("no_number", head.start())
        return None
    numbers, pos = read
    fields, pos = _qualifiers(text, pos)
    found = match_law(text, pos)
    law, end = found if found is not None else (None, pos)
    if (english and law is None) or (kind == "para" and law is not None and not is_national(law)):
        _drop("para_without_national_law", head.start())
        return _Parsed([], None, end)  # resume after the consumed span
    drafts = [_Draft(kind, n) for n in numbers]
    drafts[-1] = _Draft(kind, numbers[-1], *(fields.get(f) for f in _FIELDS))
    return _Parsed(drafts, law, end)


def _lend_target(text: str, pos: int, kind: Kind) -> int | None:
    """Offset of the next head if a law-less citation may borrow its law, else ``None``.

    Lending needs a link (``i.V.m.``, ``und``, ``sowie``, ``,``) and heads of the same kind, so a
    ``§`` is never completed with the law of an ``Art.`` (``Art. 6 i.V.m. § 280 BGB``).
    """
    link = _LINK.match(text, pos)
    sep = link or _AND.match(text, pos)
    if sep is None:
        return None
    nxt = _HEAD.match(text, sep.end())
    return sep.end() if nxt is not None and _classify(nxt.group())[0] == kind else None


def _emit(drafts: list[_Draft], law: str) -> list[Citation]:
    """Attach the law; a ``para`` draft cannot take an EU law and is skipped."""
    return [d.with_law(law) for d in drafts if d.kind == "art" or is_national(law)]


def extract_citations(text: str) -> list[Citation]:
    """Extract all citations with a resolvable law, in order of appearance.

    Handles ``§``/``§§`` (lists, ranges), ``Art.``/``Artikel``/``Article``, English forms for
    German statutes (``Section 622(2) BGB`` is ``para``), ``Abs.``/``(1)``, ``S.``, ``Nr.``,
    ``lit.``/``(f)``, ``ff.`` (dropped), ``i.V.m.`` (two citations) and long law names.

    Args:
        text: Free text; any Unicode (normalised to NFC first).

    Returns:
        Citations in order; a citation without a resolvable law is dropped (debug log).
        Never raises. The scan is linear in ``len(text)``; the result has at most
        ``max(100, len(text) // 20)`` citations (the excess is dropped in order).

    Examples:
        >>> [c.law for c in extract_citations("§§ 622, 623 BGB und Art. 6 DSGVO")]
        ['BGB', 'BGB', 'DSGVO']
        >>> extract_citations("§ 622")
        []
    """
    text = unicodedata.normalize("NFC", text)
    found: list[Citation] = []
    pending: list[_Draft] = []
    pos = 0
    while (head := _HEAD.search(text, pos)) is not None:
        parsed = _parse_at(text, head)
        if parsed is None:
            pending.clear()
            pos = head.end()
            continue
        pos = parsed.end
        if not parsed.drafts:
            pending.clear()
        elif parsed.law is not None:
            found += _emit([*pending, *parsed.drafts], parsed.law)
            pending.clear()
        elif (nxt := _lend_target(text, pos, parsed.drafts[-1].kind)) is not None:
            pending += parsed.drafts
            pos = nxt
        else:
            _drop("no_law", head.start())
            pending.clear()
    return _cap(found, len(text))


def _cap(found: list[Citation], length: int) -> list[Citation]:
    """Bound the output (range expansion could otherwise multiply the input size)."""
    cap = max(_MIN_CAP, length // _CAP_DIVISOR)
    if len(found) > cap:
        _log.debug("citations_capped", found=len(found), cap=cap)
        return found[:cap]
    return found


def parse_one(text: str) -> Citation | None:
    """Parse text that holds exactly one citation.

    Args:
        text: Free text.

    Returns:
        The citation, or ``None`` when the text holds none or several.

    Examples:
        >>> parse_one("Art. 6 DSGVO").number
        '6'
        >>> parse_one("§ 622 BGB und § 623 BGB") is None
        True
    """
    found = extract_citations(text)
    return found[0] if len(found) == 1 else None
