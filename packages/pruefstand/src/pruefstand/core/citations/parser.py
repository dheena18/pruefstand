"""Find German and EU legal citations in free text (T1.5a).

A scan over *heads* (``§``, ``Art.``, ``Section`` ...): each head is followed by a number (list),
optional qualifiers (Abs., S., Nr., lit., ``(2)``, ``ff.``) and a law name from the alias table.
A citation without a resolvable law is dropped and logged at debug level; ``i.V.m.`` lends the
law of the next citation to the one before it. Qualifiers after a list (``§§ 622, 623 Abs. 2``)
belong to its last number. Several values (``Abs. 2, 3``) keep the first.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pruefstand.core.citations.aliases import is_national, match_law
from pruefstand.core.citations.model import Citation
from pruefstand.core.logging import get_logger

_log = get_logger(__name__)
Kind = Literal["para", "art"]

_NUM = r"[0-9]{1,5}(?![0-9])(?:(?!ff?\.)[a-z](?![A-Za-zÄÖÜäöüß]))?"
_NUM_AT = re.compile(rf"\s*({_NUM})")
_HEAD = re.compile(
    r"(?:§§?|(?<![\w.])s\.|(?<!\w)(?:Paragraph|Paragraf|Sections?|Secs?\.|Artikel|Articles?"
    r"|Artt\.|Arts\.|Art\.))(?=\s*[0-9])"
)
_PLURAL_HEADS = {"§§", "Sections", "Secs.", "Articles", "Artt.", "Arts."}
_ENGLISH_HEADS = {"s.", "Section", "Sections", "Sec.", "Secs."}
_RANGE = re.compile(rf"\s*(?:bis|[–—-])\s*(?P<end>{_NUM})")
_LIST_SEP = re.compile(r"\s*(?:,|&|und|and|sowie)(?=\s*[0-9])")
_LINK = re.compile(r"\s*(?:i\.\s?V\.\s?m\.|iVm|in\s+Verbindung\s+mit)\s*")
_MAX_RANGE = 200


def _values(name: str) -> str:
    """Regex for one or more values (``2``, ``2, 3``, ``2 bis 4``); the group keeps the first."""
    return rf"(?P<{name}>{_NUM})(?:\s*(?:,|und|bis|[–—-])\s*{_NUM})*"


_QUALIFIER = re.compile(
    r"[\s,]*(?:"
    + "|".join(
        [
            r"(?:Absatz|Abs\.?)\s*" + _values("absatz"),
            r"(?:Satz|S\.|s\.)\s*" + _values("satz"),
            r"(?:Nummer|Nr\.)\s*" + _values("nummer"),
            r"(?:lit\.|Buchstabe|Buchst\.|Bst\.)\s*(?P<lit>[a-z])(?![A-Za-zÄÖÜäöüß])",
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
    drafts: list[_Draft]
    law: str | None
    end: int


def _expand(first: str, last: str) -> list[str]:
    """Expand ``first..last`` when both are plain numbers and the span is small."""
    if first.isdigit() and last.isdigit() and 0 <= int(last) - int(first) <= _MAX_RANGE:
        return [str(n) for n in range(int(first), int(last) + 1)]
    return [first, last]


def _numbers(text: str, pos: int, *, plural: bool) -> tuple[list[str], int] | None:
    """Read one number (or, for plural heads, a list with ranges) after a head."""
    numbers: list[str] = []
    while (m := _NUM_AT.match(text, pos)) is not None:
        pos = m.end()
        rng = _RANGE.match(text, pos)
        if rng is not None:
            numbers += _expand(m.group(1), rng.group("end"))
            pos = rng.end()
        else:
            numbers.append(m.group(1))
        sep = _LIST_SEP.match(text, pos) if plural else None
        if sep is None:
            break
        pos = sep.end()
    return (numbers, pos) if numbers else None


def _apply(m: re.Match[str], fields: dict[str, str]) -> bool:
    """Record one qualifier; False when it repeats a field already set."""
    for name in ("absatz", "satz", "nummer", "lit"):
        if m.group(name) is not None:
            return fields.setdefault(name, m.group(name)) == m.group(name)
    if m.group("p_num") is not None:
        if "absatz" in fields:
            return False
        fields["absatz"] = m.group("p_num")
        return True
    if m.group("p_lit") is not None:
        return fields.setdefault("lit", m.group("p_lit")) == m.group("p_lit")
    return True  # ff. / f.: dropped


def _qualifiers(text: str, pos: int) -> tuple[dict[str, str], int]:
    fields: dict[str, str] = {}
    while (m := _QUALIFIER.match(text, pos)) is not None and _apply(m, fields):
        pos = m.end()
    return fields, pos


def _classify(head: str) -> tuple[Kind, bool, bool]:
    kind: Kind = "art" if head.startswith("Art") else "para"
    return kind, head in _PLURAL_HEADS, head in _ENGLISH_HEADS


def _drop(reason: str, start: int) -> None:
    """Log a dropped citation at debug level (reason and offset only, never the text)."""
    _log.debug("citation_dropped", reason=reason, offset=start)


def _parse_at(text: str, head: re.Match[str]) -> _Parsed | None:
    kind, plural, english = _classify(head.group())
    read = _numbers(text, head.end(), plural=plural)
    if read is None:
        _drop("no_number", head.start())
        return None
    numbers, pos = read
    fields, pos = _qualifiers(text, pos)
    found = match_law(text, pos)
    law, end = found if found is not None else (None, pos)
    if english and (law is None or not is_national(law)):
        _drop("english_head_without_national_law", head.start())
        return None
    drafts = [_Draft(kind, n) for n in numbers]
    drafts[-1] = _Draft(
        kind,
        numbers[-1],
        fields.get("absatz"),
        fields.get("satz"),
        fields.get("nummer"),
        fields.get("lit"),
    )
    return _Parsed(drafts, law, end)


def extract_citations(text: str) -> list[Citation]:
    """Extract all citations with a resolvable law, in order of appearance.

    Handles ``§``/``§§`` (lists, ranges), ``Art.``/``Artikel``/``Article``, English forms for
    German statutes (``Section 622(2) BGB`` is ``para``), ``Abs.``/``(1)``, ``S.``, ``Nr.``,
    ``lit.``/``(f)``, ``ff.`` (dropped), ``i.V.m.`` (two citations) and long law names.

    Args:
        text: Free text; any Unicode (normalised to NFC first).

    Returns:
        Citations in order; a citation without a resolvable law is dropped (debug log).
        Never raises.

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
        if parsed.law is not None:
            found += [d.with_law(parsed.law) for d in (*pending, *parsed.drafts)]
            pending.clear()
            continue
        link = _LINK.match(text, pos)
        if link is not None and _HEAD.match(text, link.end()) is not None:
            pending += parsed.drafts
            pos = link.end()
            continue
        _drop("no_law", head.start())
        pending.clear()
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
