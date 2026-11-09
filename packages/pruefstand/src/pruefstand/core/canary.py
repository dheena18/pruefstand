"""Canary masking that folds the way the leak detector does (SPEC §5; shared by gate and report).

``IGNORABLE`` and ``CONFUSABLES`` are the character tables of the leak matcher
(``metrics.deterministic.folding`` re-exports them); ``mask_canaries`` cuts every canary token out
of a text, whatever hides it. Lives in ``core`` because ``gate`` and ``report`` both need it and
``gate`` may not import ``metrics``.
"""

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

_CANARY = re.compile(r"canary[a-z]{2}(?:(?!canary)[0-9a-f]){6,}")
CANARY_MASK = "CANARY-**-******"
MAX_INPUT = 8000


def _token_end(text: str, index: list[int], first_hex: int, end: int) -> int:
    """Return where the hex run of a token ends: after six digits it stops at a white-space gap."""
    for k in range(first_hex + 6, end):
        if any(c.isspace() for c in text[index[k - 1] + 1 : index[k]]):
            return k
    return end


def mask_canaries(text: str) -> str:
    """Replace every canary token in ``text`` by ``CANARY-**-******``, whatever hides it.

    The text is folded the way the detector does (NFKD, ignorable and combining characters
    dropped, case folded, look-alike letters mapped, only letters and digits kept) and searched for
    ``canary`` + two letters + at least six hex digits with any separators between them. Each
    hit is cut out of the *original* text (first to last character of the token). Input beyond
    8 000 characters is ignored. Linear in the input size.

    Example:
        >>> mask_canaries("x CAN\u200bARY-VN-7f3a9c y")
        'x CANARY-**-****** y'
    """
    text = text[:MAX_INPUT]
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for part in unicodedata.normalize("NFKD", ch):
            if IGNORABLE.match(part):
                continue
            # the detector's order: casefold, then drop marks, then map look-alikes
            for folded in part.casefold():
                if unicodedata.category(folded) == "Mn":
                    continue
                for letter in folded.translate(CONFUSABLES):
                    if letter.isalnum():
                        chars.append(letter)
                        index.append(i)
    out: list[str] = []
    pos = 0
    for match in _CANARY.finditer("".join(chars)):
        last = _token_end(text, index, match.start() + len("canary") + 2, match.end())
        start, end = index[match.start()], index[last - 1] + 1
        out.append(text[pos:start])
        out.append(CANARY_MASK)
        pos = end
    out.append(text[pos:])
    return "".join(out)
