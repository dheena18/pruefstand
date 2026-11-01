"""umlaut_translit: ä/ö/ü to ae/oe/ue (T4.4)."""

import numpy as np
import pytest

from pruefstand.perturb.umlaut_translit import UmlautTranslit

P = UmlautTranslit()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Welche Gebühren fallen an?", "Welche Gebuehren fallen an?"),
        ("Übermäßige Kündigung", "Uebermaeßige Kuendigung"),
        ("Öffentliche Ärzte", "Oeffentliche Aerzte"),
        ("Gilt § 622 BGB für Größe?", "Gilt § 622 BGB fuer Groeße?"),
    ],
)
def test_translit(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


def test_no_umlaut_is_unchanged() -> None:
    result = P.apply("Wie lang ist die Frist nach § 622 BGB?", RNG)
    assert not result.changed
    assert result.text == "Wie lang ist die Frist nach § 622 BGB?"


def test_decomposed_umlaut_is_folded_first() -> None:
    assert P.apply("Gebühren", RNG).text == "Gebuehren"


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("umlaut_translit", False)
    assert P.version
