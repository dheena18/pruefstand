"""GermanAnalyzer end to end: stopwords, abbreviations, numbers, stemming, compounds (T3.3)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rag_demo.analysis.analyzer import GermanAnalyzer, main

FULL = GermanAnalyzer(compound_split=True, stemmer="snowball_de")
NO_SPLIT = GermanAnalyzer(compound_split=False, stemmer="snowball_de")
PLAIN = GermanAnalyzer(compound_split=False, stemmer="none")


def test_compound_parts_meet_the_free_text_query() -> None:
    doc = set(FULL.tokens("Kündigungsschutzgesetz"))
    query = set(FULL.tokens("Gesetz zum Schutz vor Kündigungen"))
    assert query & doc >= set(FULL.tokens("Schutz Gesetz Kündigung"))


def test_without_compound_split_the_two_sides_do_not_meet() -> None:
    doc = set(NO_SPLIT.tokens("Kündigungsschutzgesetz"))
    query = set(NO_SPLIT.tokens("Gesetz zum Schutz vor Kündigungen"))
    assert query & doc == set()


def test_the_original_token_is_emitted_before_its_parts() -> None:
    plain_split = GermanAnalyzer(compound_split=True, stemmer="none")
    assert plain_split.tokens("Kündigungsschutzgesetz") == [
        "kuendigungsschutzgesetz",
        "kuendigung",
        "schutz",
        "gesetz",
    ]


def test_stemming_conflates_inflections() -> None:
    assert FULL.tokens("Kündigungen") == FULL.tokens("Kündigung")
    assert FULL.tokens("Gebühren") == FULL.tokens("Gebuehren")


def test_paragraph_reference_without_stemming() -> None:
    tokens = PLAIN.tokens("§ 622 Abs. 2 BGB")
    assert {"§", "622", "absatz", "2", "bgb"} <= set(tokens)


def test_function_abbreviations_are_expanded() -> None:
    assert "verbindung" in PLAIN.tokens("i.V.m.")
    assert "nummer" in PLAIN.tokens("Nr. 5")
    assert "gegebenenfalls" in PLAIN.tokens("ggf. verlängert")


def test_law_abbreviations_stay() -> None:
    assert "bgb" in PLAIN.tokens("BGB")
    assert "buergerliches" not in PLAIN.tokens("BGB")


def test_stopwords_are_dropped() -> None:
    assert PLAIN.tokens("Der Vertrag und die Frist") == ["vertrag", "frist"]
    assert PLAIN.tokens("für über") == []


@pytest.mark.parametrize("text", ["1.000,50 €", "1000.50 EUR"])
def test_amounts_become_number_and_eur(text: str) -> None:
    assert FULL.tokens(text) == PLAIN.tokens(text) == ["1000.50", "eur"]


def test_numbers_are_not_stemmed() -> None:
    assert FULL.tokens("626a") == ["626a"]


def test_empty_text_gives_no_tokens() -> None:
    assert FULL.tokens("") == []


def test_main_prints_the_token_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Kündigungsschutzgesetz"]) == 0
    printed = capsys.readouterr().out
    assert "schutz" in printed
    assert "gesetz" in printed


@given(st.text())
def test_tokens_are_deterministic_and_never_raise(text: str) -> None:
    first = FULL.tokens(text)
    assert first == FULL.tokens(text)
    assert all(first)


def test_fold_umlauts_has_no_effect_when_the_snowball_stemmer_is_on() -> None:
    """Snowball German folds ä, ö, ü, ue itself, so the flag only matters with stemmer none."""
    text = "Gebühren Gebuehren Kündigungen Kuendigungen"
    off = GermanAnalyzer(compound_split=False, stemmer="snowball_de", fold_umlauts=False)
    assert off.tokens(text) == NO_SPLIT.tokens(text)


def test_overlong_tokens_are_not_stemmed() -> None:
    word = "a" * 80 + "en"
    assert NO_SPLIT.tokens(word) == [word]
