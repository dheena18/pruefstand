"""eszett: ß to ss (T4.4)."""

import numpy as np
import pytest

from pruefstand.perturb.eszett import Eszett

P = Eszett()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Straße", "Strasse"),
        ("Gemäß § 3", "Gemäss § 3"),
        ("GROẞE Frist", "GROSSE Frist"),
        ("Übermäßige Kündigung", "Übermässige Kündigung"),
    ],
)
def test_eszett(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


def test_without_eszett_is_unchanged() -> None:
    result = P.apply("Gebühren nach § 3", RNG)
    assert not result.changed
    assert result.text == "Gebühren nach § 3"


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("eszett", False)
