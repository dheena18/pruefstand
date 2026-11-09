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


def test_all_caps_abs_and_nr_stay() -> None:
    """``Abs.`` / ``Nr.`` only match in their usual spelling (no ``ABS.`` brake system)."""
    assert not P.apply("ABS. und NR. bleiben", RNG).changed


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Abs.Nr.", "Absatz Nummer"), ("bzw.ggf.", "beziehungsweise gegebenenfalls")],
)
def test_glued_abbreviations_are_fully_expanded_and_stable(text: str, expected: str) -> None:
    once = P.apply(text, RNG).text
    assert once == expected
    assert not P.apply(once, RNG).changed


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Z. B. Azubis", "Zum Beispiel Azubis"),
        ("Z.B. Azubis", "Zum Beispiel Azubis"),
        ("Ggf. gilt das nicht. Bzw. doch", "Gegebenenfalls gilt das nicht. Beziehungsweise doch"),
        ("I.V.m. § 1", "In Verbindung mit § 1"),
        ("usw. bzw.ggf.", "und so weiter beziehungsweise gegebenenfalls"),
        ("Azubis, Praktikanten usw.", "Azubis, Praktikanten und so weiter"),
        ("Das gilt (Z. B. hier)", "Das gilt (Zum Beispiel hier)"),
    ],
)
def test_capitalised_abbreviations_and_usw_are_expanded(text: str, expected: str) -> None:
    once = P.apply(text, RNG).text
    assert once == expected
    assert not P.apply(once, RNG).changed
