"""``abbreviations``: Abs., Nr., ggf., i.V.m., z. B., bzw. written out."""

import re

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_FULL = {
    "Abs.": "Absatz",
    "Nr.": "Nummer",
    "ggf.": "gegebenenfalls",
    "iVm": "in Verbindung mit",
    "zB": "zum Beispiel",
    "bzw.": "beziehungsweise",
}
_ABBREVIATION = re.compile(r"(?<![\w.])(?:Abs\.|Nr\.|ggf\.|i\.\s?V\.\s?m\.|z\.\s?B\.|bzw\.)")


def _expand(m: re.Match[str]) -> str:
    found = m.group(0)
    word = _FULL[found.replace(" ", "").replace(".", "") if found[0] in "iz" else found]
    following = m.string[m.end() : m.end() + 1]
    needs_space = bool(following) and (following.isalnum() or following in "§(€")
    return word + " " if needs_space else word


class Abbreviations:
    """Write out the common legal abbreviations."""

    name = "abbreviations"
    version = "1"
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
        return finish(source, _ABBREVIATION.sub(_expand, source))
