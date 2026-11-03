"""Abbreviation expansion respects word boundaries (T3.3 review regressions)."""

import pytest

from rag_demo.analysis.abbreviations import expand_abbreviations
from rag_demo.analysis.analyzer import GermanAnalyzer

PLAIN = GermanAnalyzer(compound_split=False, stemmer="none")


def test_u_dot_before_a_word_starting_with_a_is_not_unter_anderem() -> None:
    assert PLAIN.tokens("Gesetz u. Arbeit") == ["gesetz", "u", "arbeit"]


def test_s_dot_before_a_word_starting_with_u_is_not_siehe_unten() -> None:
    assert "urteil" in PLAIN.tokens("s. Urteil")
    assert "unten" not in PLAIN.tokens("s. Urteil")


def test_d_dot_before_a_word_starting_with_h_is_not_das_heisst() -> None:
    tokens = PLAIN.tokens("vgl. d. Haftung")
    assert "haftung" in tokens
    assert "heisst" not in tokens


@pytest.mark.parametrize(
    ("text", "expanded"),
    [
        ("u.a. Fristen", "unter anderem"),
        ("d. h. morgen", "das heißt"),
        ("s.u. Absatz", "siehe unten"),
    ],
)
def test_real_abbreviations_still_expand(text: str, expanded: str) -> None:
    assert expanded in expand_abbreviations(text.lower())
