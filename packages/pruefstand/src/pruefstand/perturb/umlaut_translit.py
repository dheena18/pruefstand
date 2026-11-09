"""``umlaut_translit``: ä, ö, ü (and capitals) to ae, oe, ue; ß is left to ``eszett``.

A capital umlaut next to another capital (``ÄRGER``, ``GRÖSSE``) becomes ``AE`` / ``OE`` / ``UE``,
not ``Ae`` (``AeRGER``); in ``Ärger`` it stays ``Ae`` (T4.4a, D891).
"""

import re

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_TABLE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
_CAPITAL = re.compile("[ÄÖÜ]")
_PAIR = {"Ä": "A", "Ö": "O", "Ü": "U"}


def _capital(m: re.Match[str]) -> str:
    """``Ae`` normally, ``AE`` when a neighbouring letter is a capital too (all-caps word)."""
    text, at = m.string, m.start()
    shout = text[at + 1 : at + 2].isupper() or text[max(0, at - 1) : at].isupper()
    return _PAIR[m.group()] + ("E" if shout else "e")


class UmlautTranslit:
    """Transliterate umlauts the way users type them without a German keyboard layout."""

    name = "umlaut_translit"
    version = "2"
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
        return finish(source, _CAPITAL.sub(_capital, source).translate(_TABLE))
