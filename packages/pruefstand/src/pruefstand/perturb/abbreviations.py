"""``abbreviations``: Abs., Nr., ggf., i.V.m., z. B., bzw., usw. written out.

The lower-case abbreviations also match capitalised (``Z. B.`` at a sentence start becomes
``Zum Beispiel``, T4.4a, D891).
"""

import re

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_FULL = {  # key: the abbreviation without blanks and dots, case-folded
    "abs": "Absatz",
    "nr": "Nummer",
    "ggf": "gegebenenfalls",
    "ivm": "in Verbindung mit",
    "zb": "zum Beispiel",
    "bzw": "beziehungsweise",
    "usw": "und so weiter",
}
_ABBREVIATION = re.compile(
    r"(?<![\w.])(?:Abs\.|Nr\.|(?i:ggf\.|i\.\s?V\.\s?m\.|z\.\s?B\.|bzw\.|usw\.))"
)

_MAX_PASSES = 4


def _expand(m: re.Match[str]) -> str:
    found = m.group(0)
    word = _FULL[re.sub(r"[\s.]", "", found).casefold()]
    letters = re.sub(r"[\s.]", "", found)
    if len(letters) >= 3 and letters.isupper():
        word = word.upper()  # ``USW.`` -> ``UND SO WEITER``
    elif found[0].isupper():
        word = word[0].upper() + word[1:]  # sentence start: ``Z. B.`` -> ``Zum Beispiel``
    rest = m.string[m.end() :].lstrip(" ")
    if letters.casefold() == "usw" and (not rest or rest[0].isupper() or rest[0] == "\n"):
        word += "."  # ``usw.`` closes the sentence: keep the full stop
    following = m.string[m.end() : m.end() + 1]
    needs_space = bool(following) and (following.isalnum() or following in "§(€")
    return word + " " if needs_space else word


class Abbreviations:
    """Write out the common legal abbreviations."""

    name = "abbreviations"
    version = "2"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Expand each abbreviation.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when no abbreviation occurs.

        Examples:
            >>> Abbreviations().apply("Abs. 2 Nr. 1", np.random.default_rng(0)).text
            'Absatz 2 Nummer 1'
        """
        del rng  # deterministic rule
        source = nfc(text)
        out = source
        for _ in range(_MAX_PASSES):  # glued ones (Abs.Nr.) only match after the first expansion
            expanded = _ABBREVIATION.sub(_expand, out)
            if expanded == out:
                break
            out = expanded
        return finish(source, out)
