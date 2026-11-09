"""citation_style: § / Art. citations written out (T4.4)."""

import numpy as np
import pytest

from pruefstand.core.citations.aliases import law_aliases
from pruefstand.perturb.citation_style import CitationStyle, genitive_phrase

P = CitationStyle()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 622 BGB", "Paragraph 622 des Bürgerlichen Gesetzbuchs"),
        ("§ 1 KSchG", "Paragraph 1 des Kündigungsschutzgesetzes"),
        ("Art. 6 DSGVO", "Artikel 6 der Datenschutz-Grundverordnung"),
        ("§ 622 Abs. 2 BGB", "Paragraph 622 Absatz 2 des Bürgerlichen Gesetzbuchs"),
        (
            "Art. 6 Abs. 1 lit. a DSGVO",
            "Artikel 6 Absatz 1 Buchstabe a der Datenschutz-Grundverordnung",
        ),
        (
            "§ 3 Abs. 1 S. 2 Nr. 4 BGB",
            "Paragraph 3 Absatz 1 Satz 2 Nummer 4 des Bürgerlichen Gesetzbuchs",
        ),
        ("Gilt § 622 des BGB?", "Gilt Paragraph 622 des Bürgerlichen Gesetzbuchs?"),
        ("Art. 5 GG", "Artikel 5 des Grundgesetzes"),
        ("Art. 5 GDPR", "Artikel 5 der Datenschutz-Grundverordnung"),
        (
            "Gilt § 622 BGB, wenn § 1 KSchG greift?",
            "Gilt Paragraph 622 des Bürgerlichen Gesetzbuchs, "
            "wenn Paragraph 1 des Kündigungsschutzgesetzes greift?",
        ),
        ("§ 7 SGB IV", "Paragraph 7 des Vierten Buches Sozialgesetzbuch"),
    ],
)
def test_citation_style(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


@pytest.mark.parametrize(
    "text",
    [
        "§ 5 XYZG",
        "§ 622",
        "Art. 6",
        "§ 6 DSGVO",
        "§§ 622, 623 BGB",
        "Die Frist ohne Zitat",
        "§ BGB",
    ],
)
def test_unchanged(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_every_law_has_a_genitive_phrase_in_the_yaml() -> None:
    missing = [law for law in law_aliases().all_laws() if genitive_phrase(law) is None]
    assert missing == []


def test_genitive_phrase_unknown_law() -> None:
    assert genitive_phrase("XYZG") is None


def test_genitive_phrases_start_with_an_article() -> None:
    for law in law_aliases().all_laws():
        phrase = genitive_phrase(law)
        assert phrase is not None
        assert phrase.split()[0] in {"des", "der"}, law


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("citation_style", False)


@pytest.mark.parametrize(
    "text",
    [
        "Ist das DSGVO-konform?",
        "Eine BGB-Gesellschaft nach § 705 BGB-Gesellschaft",
        "Art. 6 DSGVO-VO",
    ],
)
def test_law_followed_by_hyphen_is_unchanged(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_cyberresilienz_phrase() -> None:
    assert genitive_phrase("CRA") == "der Cyberresilienz-Verordnung"


@pytest.mark.parametrize(
    "text",
    [
        "§ 622 BGB–Gesellschaft",
        "Art. 6 DSGVO–konform",
        "§ 1 KSchG\u2011konform",
        "§ 622 BGB-Gesellschaft",
        "§ 622 BGB\u2014Gesellschaft",
    ],
)
def test_a_dash_glued_to_the_law_name_makes_a_compound_and_stays(text: str) -> None:
    assert not P.apply(text, RNG).changed


def test_a_spaced_en_dash_after_a_law_is_punctuation_and_is_rewritten() -> None:
    result = P.apply("§ 622 BGB – Kündigungsfristen", RNG)
    assert result.text == "Paragraph 622 des Bürgerlichen Gesetzbuchs – Kündigungsfristen"
