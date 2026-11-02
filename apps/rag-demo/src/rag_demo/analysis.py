"""``GermanAnalyzer`` v0: NFC, lowercase, umlaut and ß folding, simple tokeniser."""

import re
import unicodedata
from typing import Literal

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_WORD = re.compile(r"\w+")


class GermanAnalyzer:
    """Turn German text into index tokens.

    Args:
        compound_split: Must be ``False`` in v0 (compound splitting arrives with T3.3).
        stemmer: Must be ``"none"`` in v0 (``"snowball_de"`` arrives with T3.3).
        fold_umlauts: Fold ä, ö, ü, ß to ae, oe, ue, ss so "Gebühren" matches "Gebuehren".

    Raises:
        ValueError: A T3.3 feature was requested.
    """

    def __init__(
        self,
        compound_split: bool,  # noqa: FBT001  (signature fixed by interfaces.md §16)
        stemmer: Literal["snowball_de", "none"],
        fold_umlauts: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        if compound_split or stemmer != "none":
            msg = "compound splitting and stemming arrive with T3.3"
            raise ValueError(msg)
        self.fold_umlauts = fold_umlauts

    def tokens(self, text: str) -> list[str]:
        """Return the tokens of ``text``: NFC, lowercased, optionally folded, split on non-word.

        Examples:
            >>> GermanAnalyzer(False, "none").tokens("Straße & Gebühren")
            ['strasse', 'gebuehren']
        """
        lowered = unicodedata.normalize("NFC", text).lower()
        if self.fold_umlauts:
            lowered = lowered.translate(_FOLD)
        return _WORD.findall(lowered)
