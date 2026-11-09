"""Text hygiene of the HTML report: every case-, target- or branch-derived string passes ``clean``.

Jinja's autoescape handles ``< > & " '``; this module removes what escaping does not: canary
tokens (masked like the detector folds them, ``mask_canaries``), control and bidi characters, and
unbounded length. Linear in the input size.
"""

import re

from pruefstand.core.canary import CANARY_MASK, mask_canaries

MASKED = "‹masked›"  # noqa: RUF001  (the same mask as store.sanitise.REDACTED, kept free of "CANARY-")
ELLIPSIS = "…"
MAX_LINE = 200
MAX_BLOCK = 4000
_CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]"
)
_SPACE = re.compile(r"[ \t\r\n]+")
_BLANKS = re.compile(r"\n{3,}")


def masked(text: str) -> str:
    """Return ``text`` with every canary token replaced by ``MASKED`` (detector folding)."""
    return mask_canaries(text).replace(CANARY_MASK, MASKED)


def _masked(text: str) -> str:
    return mask_canaries(text).replace(CANARY_MASK, MASKED)


def clean(text: str | None, limit: int = MAX_LINE) -> str:
    """Return ``text`` as one safe line: canaries masked, control characters dropped, capped.

    Args:
        text: Untrusted text or ``None``.
        limit: Maximum characters kept before the ellipsis.

    Returns:
        The cleaned line (empty for ``None``).

    Example:
        >>> clean("a   b  c")
        'a b c'
        >>> clean("x CANARY-VN-7f3a9c y") == f"x {MASKED} y"
        True
    """
    if text is None:
        return ""
    folded = _SPACE.sub(" ", _CONTROL.sub("", _masked(text))).strip()
    return folded if len(folded) <= limit else folded[:limit].rstrip() + ELLIPSIS


def clean_block(text: str | None, limit: int = MAX_BLOCK) -> str:
    """Return ``text`` with its line breaks kept (for ``pre-wrap``), otherwise as ``clean``.

    Example:
        >>> clean_block("<b>x</b>")
        '<b>x</b>'
    """
    if text is None:
        return ""
    unified = _masked(text).replace("\r\n", "\n").replace("\r", "\n")
    kept = _BLANKS.sub("\n\n", _CONTROL.sub("", unified)).strip()
    return kept if len(kept) <= limit else kept[:limit].rstrip() + ELLIPSIS
