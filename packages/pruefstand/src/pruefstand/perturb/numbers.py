"""``numbers``: German number and currency format to the international one.

Rules (D390): ``1.000,50 €`` becomes ``1000.50 EUR``, ``13,7 %`` becomes ``13.7 %``.
A number is rewritten only when the reading is unambiguous: a thousands-grouped number
with a decimal part, with two or more groups, or with a unit next to it (``%``, ``€``,
``EUR``, ``Euro``, ``Prozent``); a plain decimal comma only with such a unit. Everything
else (``§ 622``, integers below 1000, dates) stays as it is. If any German-format number would
remain after the rewrite (``zwischen 1.000 und 5.000 €``, ``Abs. 2,3 und 13,7 %``), the whole text
is left unchanged: a half-converted sentence reads differently (D394).
"""

import re

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_NUMBER = re.compile(r"(?<![\w.,§])(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<dec>\d+))?(?!\d|[.,]\d)")
_UNIT_AFTER = re.compile(r"\s?(?:%|€|EUR(?!\w)|Euro(?!\w)|Prozent(?!\w))")
_UNIT_BEFORE = re.compile(r"(?:€|EUR|Euro)\s?$")
_EURO_AFTER_DIGIT = re.compile(r"(?<=\d)\s*€")
_EURO_BEFORE_DIGIT = re.compile(r"€\s*(?=\d)")


def _convert(m: re.Match[str]) -> str:
    integer, decimals = m.group("int"), m.group("dec")
    text = m.string
    unit = bool(
        _UNIT_AFTER.match(text, m.end())
        or _UNIT_BEFORE.search(text, max(0, m.start() - 6), m.start())
    )
    grouped = "." in integer
    if grouped:
        if decimals is None and not unit and integer.count(".") < 2:
            return m.group(0)
    elif decimals is None or not unit:
        return m.group(0)
    digits = integer.replace(".", "")
    return digits if decimals is None else f"{digits}.{decimals}"


class Numbers:
    """Rewrite German-formatted numbers and the euro sign."""

    name = "numbers"
    version = "1"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Rewrite numbers and ``€``.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when no number or euro sign applies.

        Examples:
            >>> Numbers().apply("Kosten: 1.000,50 €", np.random.default_rng(0)).text
            'Kosten: 1000.50 EUR'
        """
        del rng  # deterministic rule
        source = nfc(text)
        out = _NUMBER.sub(_convert, source)
        if any(m.group("dec") or "." in m.group("int") for m in _NUMBER.finditer(out)):
            return finish(source, source)  # a German-format number would stay: mixed readings
        out = _EURO_AFTER_DIGIT.sub(" EUR", out)
        out = _EURO_BEFORE_DIGIT.sub("EUR ", out)
        return finish(source, out.replace("€", "EUR"))
