"""``numbers``: German number and currency format to the international one.

Rules (D390): ``1.000,50 €`` becomes ``1000.50 EUR``, ``13,7 %`` becomes ``13.7 %``.
A number is rewritten only when the reading is unambiguous: a thousands-grouped number
with a decimal part, with two or more groups, or with a unit next to it (``%``, ``€``,
``EUR``, ``Euro``, ``Prozent``, ``Mio.``, ``Mrd.``, ``Tsd.``, ``Millionen``, ``Milliarden``); a
plain decimal comma only with such a unit. Everything
else (``§ 622``, integers below 1000, dates) stays as it is. If any German-format number would
remain after the rewrite (``zwischen 1.000 und 5.000 €``, ``Abs. 2,3 und 13,7 %``), the whole text
is left unchanged: a half-converted sentence reads differently (D394).

T4.4a (D891): ``10.000,- €`` becomes ``10000 EUR``, ``3,5 Mio. €`` becomes ``3.5 Mio. EUR``,
a number grouped with blanks (``1 000,50 €``, ``§ 3 100 €``) is ambiguous and stays (only ``.``
groups thousands), and ``Euro`` after a number is written
``EUR`` like ``€``. A euro sign glued to a letter or doubled (``€uro``, ``€€``) is not a currency:
the text stays. Tokens with ``://`` or ``@`` (URLs, addresses) are never touched.
"""

import re

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_GROUP = r"\."  # blanks (plain, no-break, narrow) never group: ambiguous
_NUMBER = re.compile(
    rf"(?<![\w.,§])(?<!\d[ \u00a0\u202f])(?P<int>\d{{1,3}}(?:{_GROUP}\d{{3}})+|\d+)"
    r"(?:,(?:(?P<dec>\d+)|(?P<dash>[-–]{1,2})))?(?!\d|[.,]\d)"
)
_LEFTOVER = re.compile(r"\d,\d|\d\.\d{3}(?!\d)")  # no lookbehind: glued numbers count too
_UNIT_AFTER = re.compile(
    r"\s?(?:%|€|EUR(?!\w)|Euro(?!\w)|Prozent(?!\w)|(?:Mio|Mrd|Tsd)\.|Millionen(?!\w)"
    r"|Milliarden(?!\w))"
)
_UNIT_BEFORE = re.compile(r"(?:€|EUR|Euro)\s?$")
_JUNK_EURO = re.compile(r"€(?=[^\W\d_€])|(?<=[^\W\d_])€|€€")  # €uro, x€, €€: not a currency sign
_EURO_WORD = re.compile(r"(?P<pre>\d|Mio\.|Mrd\.|Tsd\.|Millionen|Milliarden)\s*Euro(?!\w)")
_EURO_AFTER_DIGIT = re.compile(r"(?<=\d)\s*€")
_EURO_BEFORE_DIGIT = re.compile(r"€\s*(?=\d)")
_TOKEN = re.compile(r"\S+")


def _convert(m: re.Match[str]) -> str:
    integer, decimals = m.group("int"), m.group("dec")
    text = m.string
    unit = bool(
        _UNIT_AFTER.match(text, m.end())
        or _UNIT_BEFORE.search(text, max(0, m.start() - 6), m.start())
    )
    whole = decimals is None  # no decimals: an integer, or an amount written ``10.000,-``
    if "." in integer:
        if whole and not m.group("dash") and not unit and integer.count(".") < 2:
            return m.group(0)
    elif (whole and not m.group("dash")) or not unit:
        return m.group(0)
    digits = re.sub(_GROUP, "", integer)
    return digits if decimals is None else f"{digits}.{decimals}"


def _rewrite(part: str) -> str | None:
    """Rewrite one URL-free piece of text; ``None`` when the whole text must stay unchanged."""
    if _JUNK_EURO.search(part):
        return None  # ``€uro`` / ``€€``: not a currency sign
    out = _NUMBER.sub(_convert, part)
    if _LEFTOVER.search(out):
        return None  # a German-format number would stay: mixed readings
    out = _EURO_WORD.sub(r"\g<pre> EUR", out)
    out = _EURO_AFTER_DIGIT.sub(" EUR", out)
    out = _EURO_BEFORE_DIGIT.sub("EUR ", out)
    return out.replace("€", "EUR")


class Numbers:
    """Rewrite German-formatted numbers and the euro sign."""

    name = "numbers"
    version = "2"
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
        out: list[str] = []
        cursor = 0
        for token in _TOKEN.finditer(source):  # linear: a URL or address is never touched
            if "://" in token.group(0) or "@" in token.group(0):
                out.append(source[cursor : token.start()])
                out.append(token.group(0))
                cursor = token.end()
        out.append(source[cursor:])
        pieces = [(at % 2 == 1) for at in range(len(out))]
        for at, protected in enumerate(pieces):
            if not protected:
                rewritten = _rewrite(out[at])
                if rewritten is None:
                    return finish(source, source)
                out[at] = rewritten
        return finish(source, "".join(out))
