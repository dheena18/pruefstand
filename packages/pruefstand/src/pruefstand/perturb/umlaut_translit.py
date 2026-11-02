"""``umlaut_translit``: ä, ö, ü (and capitals) to ae, oe, ue; ß is left to ``eszett``."""

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_TABLE = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"},
)


class UmlautTranslit:
    """Transliterate umlauts the way users type them without a German keyboard layout."""

    name = "umlaut_translit"
    version = "1"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Replace every umlaut.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when the text has no umlaut.

        Examples:
            >>> UmlautTranslit().apply("Gebühren", np.random.default_rng(0)).text
            'Gebuehren'
        """
        del rng  # deterministic rule
        source = nfc(text)
        return finish(source, source.translate(_TABLE))
