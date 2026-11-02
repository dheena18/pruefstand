"""abbreviations: legal abbreviations written out (T4.4)."""

import numpy as np
import pytest

from pruefstand.perturb.abbreviations import Abbreviations

P = Abbreviations()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Abs. 2 Nr. 1 i.V.m. § 623", "Absatz 2 Nummer 1 in Verbindung mit § 623"),
        (
            "Gilt das ggf. auch, z. B. bei Kündigung?",
            "Gilt das gegebenenfalls auch, zum Beispiel bei Kündigung?",
        ),
        (
            "Das gilt z.B. für Azubis bzw. Praktikanten",
            "Das gilt zum Beispiel für Azubis beziehungsweise Praktikanten",
        ),
        ("§ 622 i. V. m. § 623 BGB", "§ 622 in Verbindung mit § 623 BGB"),
        ("§ 622 Abs. 2 BGB", "§ 622 Absatz 2 BGB"),
    ],
)
def test_abbreviations(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


@pytest.mark.parametrize(
    "text",
    [
        "Welche Frist gilt nach § 622 BGB?",
        "Die Bestabs. und Garnr. bleiben",
        "Das Ergebnis ist z.Bsp. offen",
    ],
)
def test_unchanged(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("abbreviations", False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i.V.m.§ 1", "in Verbindung mit § 1"),
        ("Abs.2", "Absatz 2"),
        ("ggf.(siehe oben)", "gegebenenfalls (siehe oben)"),
        ("bzw. Abs.", "beziehungsweise Absatz"),
        ("Das gilt ggf.", "Das gilt gegebenenfalls"),
        ("z. B.,", "zum Beispiel,"),
    ],
)
def test_spacing_after_expansion(text: str, expected: str) -> None:
    assert P.apply(text, RNG).text == expected


def test_capitalised_z_b_is_not_expanded() -> None:
    """Known limit (D394): only the lower-case spelling is expanded."""
    assert not P.apply("Z. B. Azubis", RNG).changed
