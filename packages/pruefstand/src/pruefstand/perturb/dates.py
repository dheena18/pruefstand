"""``dates``: ``03.10.2026`` to ``3. Oktober 2026``; invalid calendar dates stay unchanged."""

import re
from datetime import date

import numpy as np

from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip
_DATE = re.compile(r"(?<![\w.,/-])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\w|\.\d|-\d)")
_REFERENCE_BEFORE = re.compile(r"(?:§|Az\.|Aktenzeichen|Nr\.)\s*$")
_MIN_YEAR, _MAX_YEAR = 1900, 2100


def _spell(m: re.Match[str]) -> str:
    day, month, year = (int(g) for g in m.groups())
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        return m.group(0)
    if _REFERENCE_BEFORE.search(m.string, max(0, m.start() - 14), m.start()):
        return m.group(0)
    try:
        date(year, month, day)
    except ValueError:
        return m.group(0)
    return f"{day}. {_MONTHS[month - 1]} {year}"


class Dates:
    """Spell numeric German dates with the month name."""

    name = "dates"
    version = "1"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Rewrite each valid ``d.m.yyyy`` date.

        Args:
            text: The question.
            rng: Unused (the rule is deterministic).

        Returns:
            The result; ``changed`` is False when there is no valid date.

        Examples:
            >>> Dates().apply("Am 03.10.2026", np.random.default_rng(0)).text
            'Am 3. Oktober 2026'
        """
        del rng  # deterministic rule
        source = nfc(text)
        return finish(source, _DATE.sub(_spell, source))
