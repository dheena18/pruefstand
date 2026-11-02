"""``eszett``: ß to ss and capital ẞ to SS."""

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_TABLE = str.maketrans({"ß": "ss", "ẞ": "SS"})


class Eszett:
    """Replace the sharp s, as Swiss spelling and many keyboards do."""

    name = "eszett"
    version = "1"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Replace every ß.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when the text has no ß.

        Examples:
            >>> Eszett().apply("Straße", np.random.default_rng(0)).text
            'Strasse'
        """
        del rng  # deterministic rule
        source = nfc(text)
        return finish(source, source.translate(_TABLE))
