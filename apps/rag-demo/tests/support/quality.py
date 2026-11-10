"""Automatic checks of the tier-2 quality questions (T3.7): citation, key fact, answer language.

The checks are deliberately strict and never fill the human verdict (S4): the citation must be in
the response's ``citations`` (not only somewhere in the answer text), a key fact must occur as
whole words in the normalised answer, and the language must be recognisable, never assumed.
"""

import re
from collections.abc import Mapping, Sequence

from support.canaries import normalise

_NORM = re.compile(
    r"(?:§|Art\.|Artikel|Article)\s*(\d+)[^§\n]{0,40}?\b(BGB|ArbZG|KSchG|DSGVO|GDPR|BDSG)\b"
)
_ALIAS = {"GDPR": "DSGVO"}
_DE = frozenset(
    [
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "und",
        "ist",
        "nicht",
        "eine",
        "einer",
        "einem",
        "wird",
        "werden",
        "muss",
        "darf",
        "sich",
        "von",
        "zu",
        "mit",
        "für",
        "auf",
        "bei",
        "wenn",
        "oder",
        "sind",
        "nach",
        "dies",
        "diese",
    ]
)
_EN = frozenset(
    [
        "the",
        "and",
        "is",
        "are",
        "of",
        "to",
        "that",
        "for",
        "with",
        "by",
        "or",
        "be",
        "must",
        "may",
        "not",
        "this",
        "which",
        "only",
        "if",
        "such",
        "as",
    ]
)
_WORDS = re.compile(r"[^\W\d_]+")
MIN_FUNCTION_WORDS = 2


def norms(text: str) -> set[tuple[str, str]]:
    """``(number, law)`` of every norm citation in ``text`` (``Article 6 GDPR`` = ``Art. 6 DSGVO``).

    Examples:
        >>> sorted(norms("Siehe § 622 Abs. 2 Nr. 1 BGB und Article 6 GDPR."))
        [('6', 'DSGVO'), ('622', 'BGB')]
    """
    return {(m.group(1), _ALIAS.get(m.group(2), m.group(2))) for m in _NORM.finditer(text)}


def cites(citations: Sequence[str], expected: Sequence[str]) -> bool:
    """Whether one of the ``expected`` norms is among the response's ``citations``.

    Examples:
        >>> cites(["§ 622 Abs. 2 Nr. 1 BGB"], ["§ 622 BGB"])
        True
        >>> cites([], ["§ 622 BGB"])
        False
    """
    found = set().union(*(norms(c) for c in citations)) if citations else set()
    wanted = set().union(*(norms(e) for e in expected)) if expected else set()
    return bool(found & wanted)


def has_fact(answer: str, facts: Sequence[str]) -> bool:
    """Whether one key fact occurs as whole words in the normalised answer.

    Examples:
        >>> has_fact("Gründe in der Person des Arbeitnehmers", ["person"])
        True
        >>> has_fact("personenbezogene Daten", ["person"])
        False
        >>> has_fact("mindestens elf Stunden", ["11 stunden"])
        True
    """
    text = normalise(answer)
    return any(re.search(rf"(?<!\w){re.escape(normalise(f))}(?!\w)", text) for f in facts)


def answer_language(text: str) -> str:
    """``"de"`` or ``"en"`` by function words, ``"unknown"`` when too few or tied (never a default).

    Examples:
        >>> answer_language("Die Frist beträgt einen Monat und ist nicht verlängerbar.")
        'de'
        >>> answer_language("The processing is lawful only if one of the conditions applies.")
        'en'
        >>> answer_language("§ 622 BGB")
        'unknown'
    """
    words = [w.casefold() for w in _WORDS.findall(text)]
    de = sum(w in _DE for w in words)
    en = sum(w in _EN for w in words)
    if max(de, en) < MIN_FUNCTION_WORDS or de == en:
        return "unknown"
    return "de" if de > en else "en"


def grade(row: Mapping[str, object], answer: str, citations: Sequence[str]) -> dict[str, bool]:
    """The automatic checks of one question row of ``questions_de.yaml``."""
    expected = [str(c) for c in row["citation"]]  # type: ignore[attr-defined]  # YAML list
    facts = [str(f) for f in row["key_facts"]]  # type: ignore[attr-defined]  # YAML list
    checks = {
        "citation": cites(citations, expected),
        "key_fact": has_fact(answer, facts),
        "language": answer_language(answer) == row["lang"],
    }
    return {**checks, "passed": all(checks.values())}
