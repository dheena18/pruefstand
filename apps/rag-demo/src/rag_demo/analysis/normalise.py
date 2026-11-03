"""Normalisation primitives: NFC and lowercase, ß/umlaut folding, tokeniser, German numbers."""

import re
import unicodedata

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
# Thousands dots and an optional decimal comma: "1.000,50" and "12.345.678", not dates "01.02.2024".
_THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d|\.\d|,\d)")
_DECIMAL_COMMA = re.compile(r"(?<![\d,])\d+,\d+(?![\d,])")
_TOKEN = re.compile(r"§|\d+\.\d+|[^\W_]+")


def nfc_lower(text: str) -> str:
    """Return ``text`` in Unicode NFC, lowercased.

    Examples:
        >>> nfc_lower("ÄPFEL")
        'äpfel'
    """
    return unicodedata.normalize("NFC", text).lower()


def fold(text: str) -> str:
    """Fold ä, ö, ü, ß to ae, oe, ue, ss (lowercase input).

    Examples:
        >>> fold("gebühren straße")
        'gebuehren strasse'
    """
    return text.translate(_FOLD)


def normalise_numbers(text: str) -> str:
    """Rewrite German number notation: thousands dots removed, decimal comma to a dot.

    Examples:
        >>> normalise_numbers("1.000,50 € und 3,5 Prozent")
        '1000.50 € und 3.5 Prozent'
        >>> normalise_numbers("am 01.02.2024")
        'am 01.02.2024'
    """
    text = _THOUSANDS.sub(lambda m: m.group(0).replace(".", "").replace(",", "."), text)
    return _DECIMAL_COMMA.sub(lambda m: m.group(0).replace(",", "."), text)


def tokenise(text: str) -> list[str]:
    """Split into lowercase tokens; keeps ``§``, numbers (``622``, ``626a``, ``1000.50``).

    Examples:
        >>> tokenise("§ 622 Abs. 2 BGB")
        ['§', '622', 'abs', '2', 'bgb']
    """
    return _TOKEN.findall(nfc_lower(text))
