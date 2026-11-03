"""Normalisation: NFC, folding, tokeniser, numbers (T3.3; T1.13 cases moved)."""

from hypothesis import given
from hypothesis import strategies as st

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.normalise import normalise_numbers, tokenise

A = GermanAnalyzer(compound_split=False, stemmer="none")


def test_umlaut_transliteration_matches() -> None:
    assert A.tokens("Gebühren") == A.tokens("Gebuehren") == ["gebuehren"]


def test_sharp_s_matches_ss() -> None:
    assert A.tokens("Straße") == A.tokens("Strasse") == ["strasse"]


def test_nfd_input_equals_nfc_input() -> None:
    assert A.tokens("Kündigung") == A.tokens("Kündigung") == ["kuendigung"]


def test_without_folding_umlauts_stay() -> None:
    plain = GermanAnalyzer(compound_split=False, stemmer="none", fold_umlauts=False)
    assert plain.tokens("Gebühren") == ["gebühren"]
    assert plain.tokens("Gebühren") != plain.tokens("Gebuehren")


def test_tokeniser_keeps_paragraph_sign_and_numbers() -> None:
    assert tokenise("§ 622 Abs. 2 BGB; § 626a") == ["§", "622", "abs", "2", "bgb", "§", "626a"]


def test_tokeniser_splits_on_punctuation_and_underscore() -> None:
    assert tokenise("vier_Wochen, (Frist).") == ["vier", "wochen", "frist"]


def test_german_number_format_is_normalised() -> None:
    assert normalise_numbers("1.000,50 €") == "1000.50 €"
    assert normalise_numbers("12.345.678") == "12345678"
    assert normalise_numbers("3,5 Prozent") == "3.5 Prozent"


def test_dates_and_plain_decimals_are_left_alone() -> None:
    assert normalise_numbers("01.02.2024") == "01.02.2024"
    assert normalise_numbers("1000.50") == "1000.50"


@given(st.text())
def test_normalise_numbers_never_raises(text: str) -> None:
    assert isinstance(normalise_numbers(text), str)
    assert all(token for token in tokenise(text))
