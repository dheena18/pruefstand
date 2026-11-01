"""The ``Citation`` model, its canonical string form, and the matching / credit rules."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Citation(BaseModel):
    """One statute reference at the finest granularity the parser reads.

    ``law`` is the canonical abbreviation from ``core/data/law_aliases.yaml``
    (``GDPR`` -> ``DSGVO``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["para", "art"]
    number: str
    absatz: str | None = None
    satz: str | None = None
    nummer: str | None = None
    lit: str | None = None
    law: str


def normalise(c: Citation, granularity: Literal["default", "full"] = "default") -> str:
    """Render a citation in its canonical form.

    Args:
        c: The citation.
        granularity: ``"default"`` = ``§``/``Art.`` + Abs. + law (SPEC §4.5);
            ``"full"`` also keeps ``S.``, ``Nr.`` and ``lit.`` for display.

    Returns:
        The canonical string.

    Examples:
        >>> normalise(Citation(kind="para", number="622", absatz="2", nummer="1", law="BGB"))
        '§ 622 Abs. 2 BGB'
        >>> normalise(Citation(kind="art", number="6", absatz="1", lit="f", law="DSGVO"), "full")
        'Art. 6 Abs. 1 lit. f DSGVO'
    """
    parts = ["§" if c.kind == "para" else "Art.", c.number]
    if c.absatz is not None:
        parts += ["Abs.", c.absatz]
    if granularity == "full":
        if c.satz is not None:
            parts += ["S.", c.satz]
        if c.nummer is not None:
            parts += ["Nr.", c.nummer]
        if c.lit is not None:
            parts += ["lit.", c.lit]
    parts.append(c.law)
    return " ".join(parts)


def _same_provision(pred: Citation, gold: Citation) -> bool:
    return (pred.kind, pred.number, pred.law) == (gold.kind, gold.number, gold.law)


def citations_match(pred: Citation, gold: Citation) -> bool:
    """Decide whether a predicted citation matches a gold one (set membership).

    Rule: ``kind``, ``number`` and ``law`` are equal **and** either the gold ``absatz`` is
    ``None`` or both ``absatz`` values are equal. ``satz``, ``nummer`` and ``lit`` are ignored.

    Args:
        pred: The citation the system produced.
        gold: The reference citation.

    Returns:
        True on a match.

    Examples:
        >>> gold = Citation(kind="para", number="622", law="BGB")
        >>> citations_match(Citation(kind="para", number="622", absatz="2", law="BGB"), gold)
        True
        >>> citations_match(gold, Citation(kind="para", number="622", absatz="2", law="BGB"))
        False
    """
    return _same_provision(pred, gold) and (gold.absatz is None or pred.absatz == gold.absatz)


def citation_credit(pred: Citation, gold: Citation) -> float:
    """Credit of one prediction against one gold citation (R9 AI9-17).

    1.0 when ``citations_match``; 0.5 when kind, number and law are equal, the gold ``absatz``
    is set and the prediction has none; otherwise 0.0 (a different Abs. is 0.0).

    Args:
        pred: The citation the system produced.
        gold: The reference citation.

    Returns:
        1.0, 0.5 or 0.0.

    Examples:
        >>> gold = Citation(kind="para", number="622", absatz="2", law="BGB")
        >>> citation_credit(Citation(kind="para", number="622", law="BGB"), gold)
        0.5
        >>> citation_credit(Citation(kind="para", number="622", absatz="3", law="BGB"), gold)
        0.0
    """
    if citations_match(pred, gold):
        return 1.0
    if _same_provision(pred, gold) and pred.absatz is None:
        return 0.5
    return 0.0
