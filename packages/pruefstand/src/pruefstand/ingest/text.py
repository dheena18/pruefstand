"""Shared text helpers of the ingest loaders (T2.2; reused by T2.3 and T2.4).

All helpers are pure and run in linear time: ``str.split``/``splitlines`` and single-pass regexes
without nested quantifiers (the tests feed pathological inputs). Unicode is normalised to NFC
before whitespace is touched, so text hashes and equality do not depend on the source encoding.
"""

import re
import unicodedata

_TOKEN = re.compile(r"\w+|[^\w\s]")
_HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_])-\r?\n(?=[a-zäöüß])")


def count_tokens(text: str) -> int:
    r"""Count tokens the way every chunker of the corpus does: ``\w+`` runs and single symbols.

    The count is a cheap, model-independent size measure (it only has to be stable), not a
    model tokenizer.

    Args:
        text: Any text.

    Returns:
        Number of matches of ``\w+|[^\w\s]``.

    Examples:
        >>> count_tokens("§ 622 Abs. 2 BGB.")
        7
        >>> count_tokens("")
        0
    """
    return sum(1 for _ in _TOKEN.finditer(text))


def nfc(text: str) -> str:
    """Return ``text`` in Unicode normal form NFC.

    Examples:
        >>> nfc("Ku\u0308ndigung") == "Kündigung"
        True
    """
    return unicodedata.normalize("NFC", text)


def normalise_line(text: str) -> str:
    r"""NFC and collapse every whitespace run (including line breaks) to one space.

    Examples:
        >>> normalise_line("  Sozial \u00a0 ungerechtfertigte\nKündigungen ")
        'Sozial ungerechtfertigte Kündigungen'
    """
    return " ".join(nfc(text).split())


def normalise_whitespace(text: str) -> str:
    r"""Collapse whitespace runs inside each line, drop blank lines, keep the line structure.

    Line breaks stay because ``(1) ... (2) ...`` Absätze and list items sit on their own lines.
    Non-breaking and other Unicode spaces count as whitespace.

    Examples:
        >>> normalise_whitespace("  (1)  Das \u00a0 Ende. \n\n (2)   Zwei  ")
        '(1) Das Ende.\n(2) Zwei'
    """
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def normalise_text(text: str) -> str:
    r"""NFC, then :func:`normalise_whitespace`. The standard clean-up of every loader.

    Examples:
        >>> normalise_text("Ku\u0308ndigung \u00a0 und\n\n Frist")
        'Kündigung und\nFrist'
    """
    return normalise_whitespace(nfc(text))


def join_hyphenation(text: str) -> str:
    r"""Join words split by a hyphen at a line end (``Kündi-\ngung``).

    Kept here for T2.3 (court decisions) and T2.4 (EUR-Lex), whose text wraps at line ends; the
    GII loader does not need it.

    Only a letter before the hyphen and a lower-case letter after the break are joined, so
    ``Ost-\nWest`` (a capital) and ``1-\n2`` keep their hyphen.

    Examples:
        >>> join_hyphenation("Kündi-\ngung der Arbeits-\nverhältnisse")
        'Kündigung der Arbeitsverhältnisse'
    """
    return _HYPHEN_BREAK.sub("", text)
