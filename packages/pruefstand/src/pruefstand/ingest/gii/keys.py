"""Citation keys and document-id slugs of GII norms."""

import re
from typing import Literal

from pruefstand.core.citations import normalise, parse_one
from pruefstand.core.citations.aliases import resolve_law
from pruefstand.ingest.gii.errors import CitationKeyError

Kind = Literal["para", "art"]
_SLUG_SEP = re.compile(r"[^a-z0-9]+")
_YEAR_SUFFIX = re.compile(r"\s+\d{4}\Z")


def slug_of(law: str) -> str:
    """Return the ASCII slug of a law abbreviation (``"SGB IV"`` -> ``"sgb-iv"``).

    Examples:
        >>> slug_of("SGB IV")
        'sgb-iv'
    """
    return _SLUG_SEP.sub("-", law.casefold()).strip("-")


def resolve_jurabk(jurabk: str) -> str | None:
    """Map the ``<jurabk>`` of a GII norm to the canonical abbreviation of ``law_aliases.yaml``.

    GII writes the abbreviation of a law that was re-enacted with a year (``"BDSG 2018"``,
    ``"VVG 2008"``) and uses odd spellings for a few others (``"BGBEG"``, ``"SGB 4"``); the
    latter are aliases in the YAML, the year suffix is stripped here.

    Args:
        jurabk: The text of ``<jurabk>``.

    Returns:
        The canonical abbreviation, or ``None`` when the law is unknown.

    Examples:
        >>> resolve_jurabk("BDSG 2018")
        'BDSG'
        >>> resolve_jurabk("SGB 4")
        'SGB IV'
    """
    return resolve_law(jurabk) or resolve_law(_YEAR_SUFFIX.sub("", jurabk))


def citation_key(kind: Kind, number: str, law: str) -> str:
    """Build the normalised citation key (``"§ 622 BGB"``, ``"Art. 1 EGBGB"``) of a norm.

    The key is built from the structured XML fields and then passed through
    :func:`pruefstand.core.citations.parse_one` and :func:`~pruefstand.core.citations.normalise`,
    so it is exactly what the citation metrics produce for the same text.

    Args:
        kind: ``"para"`` for a § or ``"art"`` for an Artikel.
        number: The number with an optional letter, e.g. ``"626a"``.
        law: Canonical abbreviation from ``law_aliases.yaml``.

    Returns:
        The key.

    Raises:
        CitationKeyError: The text does not parse to exactly this provision (unknown law, ...).

    Examples:
        >>> citation_key("para", "622", "BGB")
        '§ 622 BGB'
    """
    head = "§" if kind == "para" else "Art."
    cite = parse_one(f"{head} {number} {law}")
    if cite is None or cite.kind != kind or cite.number != number.casefold() or cite.law != law:
        msg = f"cannot build a citation key from {head} {number} {law}"
        raise CitationKeyError(msg)
    return normalise(cite)
