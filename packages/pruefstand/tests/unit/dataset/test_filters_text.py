"""Copy rules and the "der Text" rule of ``check_overlap`` (T4.3), on real law text."""

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from testsupport.qa_support import as_chunk, chunk

from pruefstand.core.enums import Lang
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.filters_text import (
    check_overlap,
    longest_common_run,
    overlap_ratio,
    refers_to_text,
    words,
)

CHUNK = chunk("gii-bgb-622#0")
COPY = (
    "Mit welcher Frist von vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats "
    "kann ich kündigen?"
)
FRESH = "Wie lange vorher muss ich als Arbeitnehmer kündigen?"


def _cand(question: str, lang: Lang = Lang.DE) -> QACandidate:
    return QACandidate(
        question=question,
        answer="Vier Wochen.",
        citation="§ 622 Abs. 1 BGB",
        chunk_id=CHUNK.chunk_id,
        prompt_version="qa_factual_de_v1",
        lang=lang,
    )


def test_a_question_that_copies_the_chunk_is_rejected() -> None:
    result = check_overlap(_cand(COPY), CHUNK, 0.0)
    assert not result.kept
    assert result.reasons == ("ngram_overlap", "long_copy")


def test_a_fresh_question_is_kept() -> None:
    result = check_overlap(_cand(FRESH), CHUNK, 0.0)
    assert result.kept
    assert result.reasons == ()


def test_nfc_and_nfd_spellings_are_equal() -> None:
    decomposed = unicodedata.normalize("NFD", CHUNK.text)
    assert decomposed != CHUNK.text
    assert words(decomposed) == words(CHUNK.text)
    assert (
        "ngram_overlap" in check_overlap(_cand(COPY), as_chunk(CHUNK, text=decomposed), 0.0).reasons
    )
    nfd_question = unicodedata.normalize("NFD", COPY)
    assert "ngram_overlap" in check_overlap(_cand(nfd_question), CHUNK, 0.0).reasons


def test_punctuation_and_case_do_not_hide_a_copy() -> None:
    sneaky = "FRIST von vier Wochen -- zum Fünfzehnten, oder zum Ende; eines Kalendermonats?"
    assert "ngram_overlap" in check_overlap(_cand(sneaky), CHUNK, 0.0).reasons


def test_five_shared_words_are_no_six_gram() -> None:
    question = "Gilt eine Frist von vier Wochen auch für Arbeiter?"
    assert check_overlap(_cand(question), CHUNK, 0.0).kept
    assert overlap_ratio(words(question), words(CHUNK.text)) == 0.0


def test_a_six_word_copy_is_rejected_but_not_a_long_copy() -> None:
    question = "Kann man bei einer Frist von vier Wochen zum Fünfzehnten kündigen?"
    result = check_overlap(_cand(question), CHUNK, 0.0)
    assert result.reasons == ("ngram_overlap",)
    assert longest_common_run(words(question), words(CHUNK.text)) == 7


def test_the_threshold_allows_a_share_of_shared_six_grams() -> None:
    question = "Kann man bei einer Frist von vier Wochen zum Fünfzehnten kündigen?"
    share = overlap_ratio(words(question), words(CHUNK.text))
    assert 0.0 < share < 1.0
    assert check_overlap(_cand(question), CHUNK, share).kept
    assert not check_overlap(_cand(question), CHUNK, share - 0.01).kept


@pytest.mark.parametrize(
    "question",
    [
        "Was sagt der Text zur Kündigungsfrist?",
        "Welche Frist nennt der Abschnitt für Arbeiter?",
        "Wie lang ist die Frist laut Auszug?",
        "Was steht im Text über die Probezeit?",
        "Wann endet die Frist nach dem Text des Gesetzes?",
    ],
)
def test_a_question_about_the_text_is_rejected(question: str) -> None:
    assert check_overlap(_cand(question), CHUNK, 0.0).reasons == ("meta_reference",)


@pytest.mark.parametrize(
    "question",
    ["Wie lang ist die Kündigungsfrist?", "Gilt das auch für Textilarbeiter in der Probezeit?"],
)
def test_ordinary_questions_do_not_refer_to_the_text(question: str) -> None:
    assert not refers_to_text(question)


def test_english_questions_use_the_english_pattern() -> None:
    assert check_overlap(
        _cand("What does the passage say about notice?", Lang.EN), CHUNK, 0.0
    ).reasons == ("meta_reference",)
    assert check_overlap(_cand("How long is the notice period?", Lang.EN), CHUNK, 0.0).kept


def test_invalid_thresholds_are_refused() -> None:
    with pytest.raises(ConfigError):
        check_overlap(_cand(FRESH), CHUNK, 1.5)
    with pytest.raises(ConfigError):
        check_overlap(_cand(FRESH), CHUNK, 0.0, long_copy_words=1)


@settings(max_examples=60, deadline=None)
@given(question=st.text(max_size=200), threshold=st.floats(min_value=0.0, max_value=1.0))
def test_check_overlap_never_raises_and_the_share_is_a_fraction(
    question: str, threshold: float
) -> None:
    if len(question.strip()) < 3:
        return
    result = check_overlap(_cand(question), CHUNK, threshold)
    assert result.kept == (not result.reasons)
    assert 0.0 <= overlap_ratio(words(question), words(CHUNK.text)) <= 1.0


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(["frist", "vier", "wochen", "zum", "ende"]), max_size=12))
def test_a_run_never_exceeds_either_text(tokens: list[str]) -> None:
    other = words(CHUNK.text)
    assert longest_common_run(tokens, other) <= min(len(tokens), len(other))
    assert longest_common_run(tokens, tokens) == len(tokens)
