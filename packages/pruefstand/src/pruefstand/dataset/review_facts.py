"""Facts of a reference answer: numbers, paragraphs, durations (T4.7a).

``answer_fact_not_in_source`` and ``fix_lost_fact`` compare these. Digits and German number words
are one form, a unit is compared by its first four letters, and the source of an answer is the
cited Absatz of the gold documents plus the question.
"""

import re
from collections.abc import Sequence

from pruefstand.core.citations import extract_citations, parse_one
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.evidence import absatz_scope, normalise_text

_WORD_VALUE = {
    "ein": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12,
    "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17,
    "achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreißig": 30,
}  # fmt: skip
_NUMBER = "|".join(sorted(_WORD_VALUE, key=len, reverse=True))
_UNIT = r"(?:Tag\w*|Woche\w*|Monat\w*|Jahr\w*|Stunde\w*|Minute\w*)"
_FACT = re.compile(
    rf"§\s*\d+\w*|\b(?:\d+|{_NUMBER})\s+{_UNIT}|\b\d+(?:[.,]\d+)?\b",
    re.IGNORECASE,
)


def fact_keys(text: str, *, bare: bool = True) -> dict[str, str]:
    """Return ``{normalised fact: as written}`` for numbers, paragraphs and durations of ``text``.

    Digits and German number words are one form (``11 Stunden`` equals ``elf Stunden``, ``ein`` and
    ``einen`` are 1) and a unit is compared by its first four letters (``Jahren`` equals
    ``Jahre``). With ``bare`` a duration also yields its bare number, so ``acht Stunden`` knows
    ``8`` (used for the source, not for the answer).

    Examples:
        >>> sorted(fact_keys("Frist von zwei Jahren und 30 Minuten"))
        ['2', '2 jahr', '30', '30 minu']
        >>> "11 stun" in fact_keys("elf Stunden")
        True
    """
    keys: dict[str, str] = {}
    for m in _FACT.finditer(text):
        raw = m.group(0)
        words = raw.split()
        if raw.startswith("§"):
            keys.setdefault("".join(raw.split()).casefold(), raw)
        elif len(words) == 2:
            number = str(_WORD_VALUE.get(words[0].casefold(), words[0]))
            keys.setdefault(f"{number} {words[1].casefold()[:4]}", raw)
            if bare:
                keys.setdefault(number, raw)
        else:
            keys.setdefault(raw.replace(",", ".").casefold(), raw)
    return keys


def unsupported_facts(answer: str, source_text: str) -> list[str]:
    """Return the numbers, paragraphs and durations of ``answer`` that ``source_text`` lacks.

    ``source_text`` is the source chunks plus whatever else the answer may repeat (the question).

    Examples:
        >>> unsupported_facts("Drei Monate.", "Frist von zwei Wochen")
        ['Drei Monate']
        >>> unsupported_facts("Zwei Wochen.", "Frist von zwei Wochen")
        []
    """
    known = fact_keys(source_text)
    return [raw for key, raw in fact_keys(answer, bare=False).items() if key not in known]


def cited_texts(case: TestCase, pool: Sequence[Chunk]) -> list[str]:
    """Return the text the answer may rely on: the cited Absatz of each chunk, else the chunk.

    A gold citation that names an Absatz limits its provision's chunks to that Absatz (a number from
    another Absatz of the same paragraph is not supported); without an Absatz the whole chunk
    counts.
    """
    absaetze: dict[tuple[str, str, str], set[str]] = {}
    for gold in case.gold_citations:
        for c in extract_citations(gold):
            absaetze.setdefault((c.kind, c.number, c.law), set())
            if c.absatz:
                absaetze[(c.kind, c.number, c.law)].add(c.absatz)
    texts: list[str] = []
    for chunk in pool:
        key = parse_one(chunk.citation_key or "")
        wanted = absaetze.get((key.kind, key.number, key.law), set()) if key else set()
        if not wanted:
            texts.append(chunk.text)
            continue
        scopes = (absatz_scope(normalise_text(chunk.text), a) for a in sorted(wanted))
        texts.extend(sc for sc in scopes if sc is not None)
    return texts


def lost_facts(original: str, fixed: str, source_text: str) -> list[str]:
    """Return the facts of ``original`` that ``fixed`` lost.

    Facts are numbers, paragraphs and durations of ``original`` that the source text states.

    Examples:
        >>> lost_facts("Er beträgt einen Monat.", "Er beträgt vier Wochen.", "Frist: einen Monat")
        ['einen Monat']
    """
    source, kept = fact_keys(source_text), fact_keys(fixed)
    return [
        raw
        for key, raw in fact_keys(original, bare=False).items()
        if key in source and key not in kept
    ]
