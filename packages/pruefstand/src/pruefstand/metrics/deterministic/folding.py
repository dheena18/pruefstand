"""Character folding shared by the leak matcher: ignorable code points, accents, look-alikes."""

import unicodedata

from pruefstand.core.canary import CONFUSABLES

CONFUSABLES_ANY_CASE = {
    **CONFUSABLES,
    **{ord(chr(c).upper()): v for c, v in CONFUSABLES.items()},
}


def strip_marks(text: str) -> str:
    """Drop combining marks (category Mn) of an NFKD string."""
    if text.isascii():
        return text
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def fold_letters(text: str) -> str:
    """Casefold, strip accents and fold look-alikes of already-lower-case words."""
    decomposed = strip_marks(unicodedata.normalize("NFKD", text.casefold()))
    return unicodedata.normalize("NFC", decomposed.translate(CONFUSABLES))
