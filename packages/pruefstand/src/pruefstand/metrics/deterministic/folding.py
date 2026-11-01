"""Character folding shared by the leak matcher: ignorable code points, accents, look-alikes."""

import re
import unicodedata

# Cf (format) code points of Unicode 15 plus variation selectors and invisible fillers; a test
# compares this class with unicodedata so a Unicode update cannot silently open a gap.
IGNORABLE = re.compile(
    r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e"
    r"\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb\U000110bd\U000110cd\U00013430-\U0001343f"
    r"\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f"
    r"\u034f\u115f\u1160\u3164\uffa0\ufe00-\ufe0f\U000e0100-\U000e01ef"
    r"\u2800\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]"
)
_CYRILLIC_1 = "\u0430\u0435\u043a\u043c\u043d\u043e\u0440\u0441\u0442\u0443\u0445"
_CYRILLIC_2 = "\u0456\u0458\u0455\u0501\u04bb\u051b\u051d\u04cf\u04af"
_GREEK = (
    "\u03b1\u03b2\u03b3\u03b5\u03b7\u03b9\u03ba\u03bc\u03bd\u03bf\u03c1\u03c4\u03c5\u03c7\u03c9"
)
_LOOKALIKES = (  # (look-alike characters, the Latin letters they imitate)
    (_CYRILLIC_1, "aekmhopctyx"),
    (_CYRILLIC_2, "ijsdhqwly"),
    (_GREEK, "abyenikuvoptuxw"),
)
CONFUSABLES = {
    ord(c): latin for chars, ls in _LOOKALIKES for c, latin in zip(chars, ls, strict=True)
}
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
