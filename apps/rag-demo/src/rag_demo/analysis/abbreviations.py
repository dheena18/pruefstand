"""Function abbreviations expanded before tokenising; law abbreviations (BGB) stay."""

import re

ABBREVIATIONS: dict[str, str] = {
    "abs.": "absatz",
    "art.": "artikel",
    "nr.": "nummer",
    "ggf.": "gegebenenfalls",
    "i.v.m.": "in verbindung mit",
    "z.b.": "zum beispiel",
    "bzw.": "beziehungsweise",
    "d.h.": "das heißt",
    "u.a.": "unter anderem",
    "u.u.": "unter umständen",
    "s.o.": "siehe oben",
    "s.u.": "siehe unten",
    "evtl.": "eventuell",
    "inkl.": "inklusive",
    "vgl.": "vergleiche",
    "usw.": "und so weiter",
    "sog.": "sogenannte",
    "ca.": "circa",
    "mtl.": "monatlich",
    "jährl.": "jährlich",
}


def _pattern(abbreviation: str) -> str:
    """Regex for one abbreviation; blanks may follow dots, the last dot is optional."""
    escaped = r"\.\s*".join(re.escape(part) for part in abbreviation.rstrip(".").split("."))
    return escaped + (r"\.?" if "." in abbreviation.rstrip(".") else r"\.")


_REGEX = re.compile(
    r"(?<!\w)("
    + "|".join(_pattern(a) for a in sorted(ABBREVIATIONS, key=len, reverse=True))
    + r")(?![^\W\d_])"
)


def _key(matched: str) -> str:
    compact = re.sub(r"\s+", "", matched)
    return compact if compact.endswith(".") else compact + "."


def expand_abbreviations(text: str) -> str:
    """Expand function abbreviations in lowercase ``text``.

    Examples:
        >>> expand_abbreviations("§ 5 abs. 2 i. v. m. nr. 3")
        '§ 5  absatz  2  in verbindung mit   nummer  3'
    """
    return _REGEX.sub(lambda m: f" {ABBREVIATIONS[_key(m.group(1))]} ", text)
