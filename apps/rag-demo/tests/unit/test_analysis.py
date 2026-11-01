"""GermanAnalyzer v0 (T1.13 S3)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rag_demo.analysis import GermanAnalyzer

A = GermanAnalyzer(compound_split=False, stemmer="none")


def test_umlaut_transliteration_matches() -> None:
    assert A.tokens("Gebühren") == A.tokens("Gebuehren") == ["gebuehren"]


def test_sharp_s_matches_ss() -> None:
    assert A.tokens("Straße") == A.tokens("Strasse") == ["strasse"]


def test_nfd_input_equals_nfc_input() -> None:
    assert A.tokens("Kündigung") == A.tokens("Kündigung")


def test_tokeniser_splits_punctuation_and_keeps_numbers() -> None:
    assert A.tokens("§ 622 Abs. 2 BGB: vier Wochen.") == [
        "622",
        "abs",
        "2",
        "bgb",
        "vier",
        "wochen",
    ]


def test_without_folding_umlauts_stay() -> None:
    plain = GermanAnalyzer(compound_split=False, stemmer="none", fold_umlauts=False)
    assert plain.tokens("Gebühren") == ["gebühren"]


def test_stemming_and_compound_splitting_arrive_with_t3_3() -> None:
    with pytest.raises(ValueError, match="T3.3"):
        GermanAnalyzer(compound_split=True, stemmer="none")
    with pytest.raises(ValueError, match="T3.3"):
        GermanAnalyzer(compound_split=False, stemmer="snowball_de")


@given(st.text())
def test_tokens_are_lowercase_ascii_alnum_after_folding(text: str) -> None:
    for token in A.tokens(text):
        assert token == token.lower()
        assert token
