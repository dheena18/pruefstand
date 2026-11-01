"""Court classification of OLDP decisions for T2.5 tenant planning (T2.3 S5).

``jurisdiction`` is derived from the court *name* first (30 % of the sample have no
``court.jurisdiction`` value): ``Arbeitsgericht`` (Arbeits-, Landesarbeits-, Bundesarbeitsgericht),
``Sozialgericht``, ``Zivilgericht`` (Amts-, Land-, Oberlandesgericht, Kammergericht, BGH),
``Verwaltungsgericht`` (incl. Oberverwaltungsgericht, Verwaltungsgerichtshof, BVerwG),
``Finanzgericht`` (incl. BFH), ``Verfassungsgericht``; everything else is ``Sonstige``. Only a
name that matches none of these falls back to the dump's own ``court.jurisdiction`` field.

``tenant_domain`` is the coarse topic T2.5 maps to tenants: ``labour`` for labour courts,
``insurance`` when the first 4 000 characters of any other decision mention *Versicherung*
(Hausrat-, Kranken-, Rentenversicherung, Versicherungsnehmer, ...) and ``other`` otherwise. It is
a heuristic (a keyword in the head of the text), documented as such in ``docs/decisions.md``.
"""

from typing import NamedTuple

_BY_NAME: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Arbeitsgericht", ("arbeitsgericht",)),
    ("Sozialgericht", ("sozialgericht",)),
    ("Verwaltungsgericht", ("verwaltungsgericht",)),
    ("Finanzgericht", ("finanzgericht", "finanzhof")),
    ("Verfassungsgericht", ("verfassungsgericht",)),
    (
        "Zivilgericht",
        ("amtsgericht", "landgericht", "oberlandesgericht", "kammergericht", "bundesgerichtshof",
         "landesgericht"),
    ),
)  # fmt: skip
_BY_FIELD = {
    "Arbeitsgerichtsbarkeit": "Arbeitsgericht",
    "Sozialgerichtsbarkeit": "Sozialgericht",
    "Verwaltungsgerichtsbarkeit": "Verwaltungsgericht",
    "Finanzgerichtsbarkeit": "Finanzgericht",
    "Verfassungsgerichtsbarkeit": "Verfassungsgericht",
    "Ordentliche Gerichtsbarkeit": "Zivilgericht",
}
_HEAD_CHARS = 4000
OTHER_JURISDICTION = "Sonstige"


class CourtClass(NamedTuple):
    """Jurisdiction and instance level of a court (``level`` is ``""`` when unknown)."""

    jurisdiction: str
    level: str


def _level_from_name(lowered: str) -> str:
    if "bundes" in lowered:
        return "Bundesgericht"
    if "oberlandesgericht" in lowered or "kammergericht" in lowered:
        return "Oberlandesgericht"
    if "amtsgericht" in lowered:
        return "Amtsgericht"
    if "landgericht" in lowered:
        return "Landgericht"
    return ""


def classify_court(
    name: str, jurisdiction_field: str | None, level_field: str | None
) -> CourtClass:
    """Classify a court by its name, falling back to the dump's own fields.

    Args:
        name: ``court.name`` (``"Hessisches Landesarbeitsgericht"``); may be empty.
        jurisdiction_field: ``court.jurisdiction`` of the dump (``"Arbeitsgerichtsbarkeit"``) or
            ``None``; used only when the name matches no known court type.
        level_field: ``court.level_of_appeal`` of the dump or ``None``; wins over the level read
            from the name.

    Returns:
        The jurisdiction (see the module docstring) and the instance level.

    Examples:
        >>> classify_court("Landesarbeitsgericht Berlin-Brandenburg", None, None).jurisdiction
        'Arbeitsgericht'
        >>> classify_court("Unknown court", "Ordentliche Gerichtsbarkeit", None).jurisdiction
        'Zivilgericht'
        >>> classify_court("Amtsgericht Köln", None, None).level
        'Amtsgericht'
    """
    lowered = name.casefold()
    jurisdiction = next(
        (label for label, needles in _BY_NAME if any(n in lowered for n in needles)), None
    )
    if jurisdiction is None:
        jurisdiction = _BY_FIELD.get(jurisdiction_field or "", OTHER_JURISDICTION)
    return CourtClass(jurisdiction, level_field or _level_from_name(lowered))


def tenant_domain(jurisdiction: str, text: str) -> str:
    """Return ``"labour"``, ``"insurance"`` or ``"other"`` for T2.5 tenant planning.

    Args:
        jurisdiction: Result of :func:`classify_court`.
        text: The decision text; only its first 4 000 characters are read.

    Returns:
        ``labour`` for a labour court, else ``insurance`` if the head of the text contains
        *versicherung* (case-insensitive), else ``other``.

    Examples:
        >>> tenant_domain("Zivilgericht", "Streit um die Hausratsversicherung")
        'insurance'
        >>> tenant_domain("Arbeitsgericht", "Versicherung")
        'labour'
    """
    if jurisdiction == "Arbeitsgericht":
        return "labour"
    return "insurance" if "versicherung" in text[:_HEAD_CHARS].casefold() else "other"
