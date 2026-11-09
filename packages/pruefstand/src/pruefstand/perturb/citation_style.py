"""``citation_style``: ``§ 622 Abs. 2 BGB`` to ``Paragraph 622 Absatz 2 des Bürgerlichen ...``.

Law names and genitive forms come only from ``core/data/law_aliases.yaml`` (T1.5a): the genitive
phrase of a law is its alias that starts with ``des`` or ``der`` (D391). A citation whose law is
unknown, or ``§`` with an EU act, or ``§§``, stays unchanged.
"""

import re

import numpy as np

from pruefstand.core.citations.aliases import is_national, law_aliases, match_law
from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_HEAD = re.compile(r"(?<![\w§])(?P<head>§(?!§)|Art\.)\s*(?P<num>\d{1,5}(?:[a-z](?![A-Za-z0-9]))?)")
_QUALIFIER = re.compile(
    r"\s*(?:(?P<key>Abs\.|Absatz|S\.|Satz|Nr\.|Nummer)\s*(?P<n>\d{1,3}[a-z]?)"
    r"|(?P<lit>lit\.|Buchstabe)\s*(?P<c>[a-z]))(?![A-Za-z0-9])"
)
_WORD = {
    "Abs.": "Absatz",
    "Absatz": "Absatz",
    "S.": "Satz",
    "Satz": "Satz",
    "Nr.": "Nummer",
    "Nummer": "Nummer",
    "lit.": "Buchstabe",
    "Buchstabe": "Buchstabe",
}
_HEAD_WORD = {"§": "Paragraph", "Art.": "Artikel"}
_MAX_QUALIFIERS = 6
_JOINERS = (
    "-",
    "–",
    "\u2011",
    "\u2014",
)  # hyphen, en dash, non-breaking hyphen glued to a law name


def genitive_phrase(law: str) -> str | None:
    """Return the genitive phrase with article (``des Grundgesetzes``) of a canonical law.

    Args:
        law: Canonical abbreviation as in ``law_aliases.yaml`` (``"BGB"``).

    Returns:
        The first alias starting with ``des`` or ``der``, or ``None`` when the law is unknown or
        has none.

    Examples:
        >>> genitive_phrase("GG")
        'des Grundgesetzes'
        >>> genitive_phrase("XYZG") is None
        True
    """
    for alias in law_aliases().all_laws().get(law, ()):
        if alias.split(" ", 1)[0] in {"des", "der"}:
            return alias
    return None


def _qualifiers(text: str, pos: int) -> tuple[str, int]:
    parts: list[str] = []
    for _ in range(_MAX_QUALIFIERS):
        q = _QUALIFIER.match(text, pos)
        if q is None:
            break
        if q.group("key"):
            parts.append(_WORD[q.group("key")] + " " + q.group("n"))
        else:
            parts.append(_WORD[q.group("lit")] + " " + q.group("c"))
        pos = q.end()
    return "".join(f" {p}" for p in parts), pos


def _rewrite(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for head in _HEAD.finditer(text):
        if head.start() < cursor:
            continue
        quals, pos = _qualifiers(text, head.end())
        found = match_law(text, pos)
        if found is None or (head.group("head") == "§" and not is_national(found[0])):
            continue
        if text[found[1] : found[1] + 1] in _JOINERS:  # DSGVO-konform, BGB–Gesellschaft
            continue
        genitive = genitive_phrase(found[0])
        if genitive is None:
            continue
        word = _HEAD_WORD[head.group("head")]
        out.append(text[cursor : head.start()])
        out.append(f"{word} {head.group('num')}{quals} {genitive}")
        cursor = found[1]
    out.append(text[cursor:])
    return "".join(out)


class CitationStyle:
    """Write § and Art. citations out in words."""

    name = "citation_style"
    version = "2"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Rewrite each citation with a known law.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when no citation could be rewritten.

        Examples:
            >>> CitationStyle().apply("§ 1 KSchG", np.random.default_rng(0)).text
            'Paragraph 1 des Kündigungsschutzgesetzes'
        """
        del rng  # deterministic rule
        source = nfc(text)
        return finish(source, _rewrite(source))
