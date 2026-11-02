"""Helpers shared by the deterministic perturbations."""

import unicodedata

from pruefstand.core.models.perturb import PerturbResult


def nfc(text: str) -> str:
    """Return ``text`` in Unicode normal form C (decomposed umlauts become single characters)."""
    return unicodedata.normalize("NFC", text)


def finish(source: str, out: str, notes: str = "") -> PerturbResult:
    """Build the result of a perturbation.

    Args:
        source: The NFC-normalised input.
        out: The text after the rule ran.
        notes: Remark kept only when the text changed.

    Returns:
        A result whose text is NFC and whose ``changed`` compares against ``source``.
    """
    text = nfc(out)
    changed = text != source
    return PerturbResult(text=text, changed=changed, notes=notes if changed else "")
