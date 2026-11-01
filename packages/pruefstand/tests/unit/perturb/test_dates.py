"""dates: dd.mm.yyyy to "d. Monat yyyy" (T4.4)."""

import numpy as np
import pytest

from pruefstand.perturb.dates import Dates

P = Dates()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Am 03.10.2026 gilt es", "Am 3. Oktober 2026 gilt es"),
        ("Seit 1.1.2025", "Seit 1. Januar 2025"),
        ("Bis zum 31.12.2025.", "Bis zum 31. Dezember 2025."),
        ("Vom 29.02.2024 bis 01.03.2024", "Vom 29. Februar 2024 bis 1. März 2024"),
    ],
)
def test_dates(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


@pytest.mark.parametrize(
    "text",
    [
        "Am 31.02.2026",
        "Am 29.02.2025",
        "Am 00.10.2026",
        "Am 10.13.2026",
        "Gilt § 3",
        "Version 1.2.3",
        "Zahl 1.000.2026",
        "Am 03.10.20261",
    ],
)
def test_unchanged(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("dates", False)
