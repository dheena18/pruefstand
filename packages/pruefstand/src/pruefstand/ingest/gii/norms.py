"""Metadata of a GII ``<norm>`` and the decision whether it becomes a Document.

Each law file is a flat list of ``<norm>`` elements: the first one carries the law-level data
(``<standangabe>``, no ``<enbez>``), structure headings are ``<gliederungseinheit>`` norms without
text, and paragraphs have an ``<enbez>`` (``"§ 622"``). :func:`classify` returns a
:class:`Unit` (a citable § or Artikel), a :class:`Skip` (with a counted reason) or a
:class:`Reject` (an ``<enbez>`` we do not understand: a counted loader error).

Skip reasons: ``header`` (law-level norm), ``toc`` (Inhaltsübersicht), ``preamble``
(Eingangsformel), ``annex`` (Anlage, Anhang), ``range`` (``(XXXX) §§ 3 bis 6`` and
``Art 27 bis 37`` placeholders of repealed ranges), ``structure`` (headings without text),
``repealed`` and ``empty`` (decided by the loader after the text is extracted).

EGBGB nests paragraphs below articles: ``enbez="§ 1"`` inside ``gliederungsbez="Art 246a"``.
core.citations has no combined form, so such a unit gets the key of its Artikel
(``"Art. 246a EGBGB"``) and the paragraph is kept in ``Chunk.section`` (``"§ 1"``).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from lxml import etree

from pruefstand.ingest.text import normalise_line

Kind = Literal["para", "art"]
_NUM = r"(\d{1,4}[a-z]{0,3})"
_PARA = re.compile(rf"§\s*{_NUM}\Z", re.IGNORECASE)
_ART = re.compile(rf"Art(?:\.|ikel)?\s*{_NUM}\Z", re.IGNORECASE)
_RANGE = re.compile(r"\(XXXX\)|(?:§§|Art\.?)\s*\S+\s+(?:bis|und|u\.)\s", re.IGNORECASE)
_SKIP_PREFIXES = (
    ("inhaltsübersicht", "toc"),
    ("eingangsformel", "preamble"),
    ("anlage", "annex"),
    ("anhang", "annex"),
)
REPEALED = frozenset({"(weggefallen)", "(gegenstandslos)", "(aufgehoben)", "(entfallen)"})


@dataclass(frozen=True)
class NormMeta:
    """The ``<metadaten>`` of a norm, whitespace-normalised."""

    jurabk: str
    enbez: str
    titel: str
    doknr: str
    builddate: str
    has_gliederung: bool
    gliederung_bez: str


@dataclass(frozen=True)
class Unit:
    """A citable provision: ``number`` is the § or Artikel number, ``sub`` a § inside an Artikel."""

    kind: Kind
    number: str
    sub: str | None = None
    from_gliederung: bool = False

    @property
    def suffix(self) -> str:
        """The part of the doc id after the law slug (``"622"``, ``"246a-1"``)."""
        return self.number if self.sub is None else f"{self.number}-{self.sub}"

    @property
    def section(self) -> str | None:
        """``"§ 1"`` for a paragraph nested in an Artikel, else ``None``."""
        return None if self.sub is None else f"§ {self.sub}"


@dataclass(frozen=True)
class Skip:
    """A norm that is not a citable unit; ``reason`` is counted per law."""

    reason: str


@dataclass(frozen=True)
class Reject:
    """A norm that looks citable but cannot be understood: a counted loader error."""

    kind: str
    detail: str


def _text(norm: etree._Element, path: str) -> str:
    found = norm.find(path)
    return "" if found is None else normalise_line("".join(found.itertext()))


def read_meta(norm: etree._Element) -> NormMeta:
    """Read the metadata of a ``<norm>`` element."""
    return NormMeta(
        jurabk=_text(norm, "metadaten/jurabk"),
        enbez=_text(norm, "metadaten/enbez"),
        titel=_text(norm, "metadaten/titel"),
        doknr=norm.get("doknr", ""),
        builddate=norm.get("builddate", ""),
        has_gliederung=norm.find("metadaten/gliederungseinheit") is not None,
        gliederung_bez=_text(norm, "metadaten/gliederungseinheit/gliederungsbez"),
    )


def read_stand(norm: etree._Element) -> str | None:
    """Return the ``Stand`` remark of a law-level norm (``"Zuletzt geändert durch ..."``)."""
    for stand in norm.iterfind("metadaten/standangabe"):
        if _text(stand, "standtyp").casefold() == "stand":
            return _text(stand, "standkommentar") or None
    return None


def parse_builddate(value: str | None) -> date | None:
    """Parse a GII ``builddate`` (``"20260926215508"``) into a date; ``None`` if absent or invalid.

    Examples:
        >>> parse_builddate("20260926215508")
        datetime.date(2026, 9, 26)
        >>> parse_builddate(None) is None
        True
    """
    if not value or len(value) < 8:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()  # noqa: DTZ007  (a date, no zone)
    except ValueError:
        return None


def _classify_enbez(meta: NormMeta) -> Unit | Skip | Reject:
    low = meta.enbez.casefold()
    for prefix, reason in _SKIP_PREFIXES:
        if low.startswith(prefix):
            return Skip(reason)
    if _RANGE.search(meta.enbez):
        return Skip("range")
    if para := _PARA.match(meta.enbez):
        nested = _ART.match(meta.gliederung_bez)
        if nested:
            return Unit("art", nested.group(1).lower(), para.group(1).lower())
        return Unit("para", para.group(1).lower())
    if art := _ART.match(meta.enbez):
        return Unit("art", art.group(1).lower())
    return Reject("unknown_enbez", meta.enbez)


def classify(meta: NormMeta) -> Unit | Skip | Reject:
    """Decide what a norm is from its metadata (the text is checked later by the loader).

    Args:
        meta: Result of :func:`read_meta`.

    Returns:
        A :class:`Unit`, a :class:`Skip` or a :class:`Reject`.
    """
    if meta.enbez:
        return _classify_enbez(meta)
    if not meta.has_gliederung:
        return Skip("header")
    if _RANGE.search(meta.gliederung_bez):
        return Skip("range")
    if art := _ART.match(meta.gliederung_bez):
        return Unit("art", art.group(1).lower(), from_gliederung=True)
    return Skip("structure")
