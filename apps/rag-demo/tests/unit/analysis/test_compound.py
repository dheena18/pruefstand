"""Dictionary compound splitter: direct calls, no folding, no stemming (T3.3)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rag_demo.analysis import compound


def test_kuendigungsschutzgesetz_has_three_parts_with_fugen_s() -> None:
    assert compound.split("Kündigungsschutzgesetz") == ["kündigung", "schutz", "gesetz"]


def test_arbeitszeitgesetz_drops_the_fugen_s() -> None:
    assert compound.split("Arbeitszeitgesetz") == ["arbeit", "zeit", "gesetz"]


def test_rahmenvertrag_prefers_the_whole_word_over_stem_plus_fugen() -> None:
    assert compound.split("Rahmenvertrag") == ["rahmen", "vertrag"]


def test_short_word_is_unchanged() -> None:
    assert compound.split("Gesetz") == ["gesetz"]


def test_unknown_long_word_is_unchanged() -> None:
    assert compound.split("Zwiebelmuffelei") == ["zwiebelmuffelei"]


def test_transliterated_spelling_splits_too() -> None:
    assert compound.split("Kuendigungsschutzgesetz") == ["kuendigung", "schutz", "gesetz"]


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("Mietvertrag", ["miet", "vertrag"]),
        ("Datenschutzgrundverordnung", ["daten", "schutz", "grund", "verordnung"]),
        ("Gebührenordnung", ["gebühr", "ordnung"]),
        ("Kündigungsfrist", ["kündigung", "frist"]),
    ],
)
def test_legal_compounds(word: str, parts: list[str]) -> None:
    assert compound.split(word) == parts


def test_parts_are_at_least_three_characters() -> None:
    assert all(len(part) >= 3 for part in compound.split("Arbeitnehmerschutzgesetz"))


@given(st.text(max_size=40))
def test_split_is_deterministic_and_never_raises(word: str) -> None:
    assert compound.split(word) == compound.split(word)
    assert compound.split(word)
