"""Review fixes of #107: validity filters for constructed negatives, MEMERAG majority edge cases."""

from pathlib import Path

import numpy as np
import pytest
from rq2.calib_memerag import CHALLENGING, NOT_SUPPORTED, SUPPORTED, majority, sentence_label
from rq2.calib_rag import _unsupported, distractor_ok
from rq2.calib_sources import RagRow, load_germanrag
from rq2.construct import clean_span
from rq2.construct_checks import (
    coverage,
    edit_in_first_clause,
    has_answer_content,
    may_support,
    near_number,
    negation_ok,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _supported_rows() -> dict[str, RagRow]:
    rows = load_germanrag(FIXTURES / "germanrag_supported_distractors.jsonl")
    keys = ("Alstom", "Kalasha", "Buhl", "Wang Mang", "Filmempfindlichkeit", "Warschauer")
    return {next(k for k in keys if k in r.question): r for r in rows}


def test_ge_alstom_same_article_distractor_is_rejected() -> None:
    row = _supported_rows()["Alstom"]
    distractor = next(c for i, c in enumerate(row.contexts) if i != row.positive)
    assert coverage(row.answer, distractor) >= 0.6
    assert not distractor_ok(row, distractor)
    assert _unsupported(row, [], np.random.default_rng(1234)) is None


def test_kalasha_other_article_distractor_with_the_answer_is_rejected() -> None:
    row = _supported_rows()["Kalasha"]
    chitral = next(c for c in row.contexts if c.startswith("Kalasha__Chitral_"))
    assert may_support(row.answer, chitral)
    assert not distractor_ok(row, chitral)
    picked = _unsupported(row, [], np.random.default_rng(1234))
    assert picked is None or picked.inputs["kontext"] != chitral


def test_off_topic_passage_passes() -> None:
    rows = load_germanrag(FIXTURES / "germanrag_4.jsonl")
    lamp = next(r for r in rows if r.answer.startswith("Kleinspannungsglühlampen"))
    water_cannon = next(c for c in lamp.contexts if c.startswith("Wasserwerfer"))
    assert distractor_ok(lamp, water_cannon)


def test_bm25_neighbour_mentioning_the_answer_is_rejected() -> None:
    row = _supported_rows()["Kalasha"]
    greeks = next(c for c in row.contexts if c.startswith("Griechen"))
    assert not distractor_ok(row, greeks)  # names "Kalasha-mun": may support the answer


def test_clean_span_rejects_markup_and_unbalanced_brackets() -> None:
    assert clean_span("die Stadt Grenoble")
    assert clean_span("die Stadt (Isère)")
    for bad in (
        "Datei:Alpen.jpg",
        "| Einwohner = 5",
        "[[Grenoble]]",
        "Stadt (Isère",
        "Isère) liegt",
    ):
        assert not clean_span(bad)


def test_negation_only_in_the_first_clause() -> None:
    ref = "Die Konsole, die 1985 erschien, war teuer"
    assert not edit_in_first_clause(ref, "Die Konsole, die 1985 nicht erschien, war teuer")
    assert edit_in_first_clause("Die Frist ist verlängert.", "Die Frist ist nicht verlängert.")
    assert not edit_in_first_clause(
        "Bonn (das ist die alte Hauptstadt)", "Bonn (das ist nicht die alte Hauptstadt)"
    )
    assert not edit_in_first_clause(
        "Das Betreten –\xa0außer zum Entladen\xa0– sowie die Mitfahrt sind verboten.",
        "Das Betreten –\xa0außer zum Entladen\xa0– sowie die Mitfahrt sind nicht verboten.",
    )


def test_partial_needs_answer_content() -> None:
    assert not has_answer_content("die in der")
    assert has_answer_content("Patriarch von Alexandria")


def test_majority_edge_cases() -> None:
    assert majority([SUPPORTED] * 3 + [NOT_SUPPORTED] * 2) == SUPPORTED
    assert majority([NOT_SUPPORTED] * 3 + [SUPPORTED] * 2) == NOT_SUPPORTED
    assert majority([SUPPORTED, NOT_SUPPORTED]) == CHALLENGING
    assert majority([SUPPORTED, SUPPORTED, NOT_SUPPORTED, NOT_SUPPORTED]) == CHALLENGING
    assert majority([SUPPORTED, NOT_SUPPORTED, CHALLENGING, CHALLENGING, SUPPORTED]) == CHALLENGING
    assert sentence_label(SUPPORTED) == SUPPORTED
    assert sentence_label([CHALLENGING] * 3 + [SUPPORTED] * 2) == CHALLENGING


@pytest.mark.parametrize(
    ("key", "title"),
    [
        ("Buhl", "Buhl__Idaho_"),  # "vor rund 10.700 Jahren" supports "über 10.500 Jahre"
        ("Wang Mang", "Shi__Xin_"),
        ("Filmempfindlichkeit", "American_National_Standards_Institute"),
        ("Warschauer", "Bulgarische_Luftstreitkräfte"),
    ],
)
def test_second_review_near_miss_distractors_are_rejected(key: str, title: str) -> None:
    row = _supported_rows()[key]
    passage = next(c for c in row.contexts if c.startswith(title))
    assert not distractor_ok(row, passage)
    picked = _unsupported(row, [], np.random.default_rng(1234))
    assert picked is None or not picked.inputs["kontext"].startswith(title)


def test_near_number_german_format() -> None:
    assert near_number("über 10.500 Jahre", "vor rund 10.700 Jahren")
    assert near_number("9,7 Milliarden", "rund 10 Milliarden")
    assert not near_number("über 10.500 Jahre", "im Jahr 1871")


def test_span_markup_quotes_and_content() -> None:
    for bad in (
        "''kas''",
        "''Army''",
        "of",
        "offen",
        "jeweils",
        "vielmehr",
        "allesamt",
        "Schiefheit“",
    ):
        assert not clean_span(bad), bad
    assert not clean_span("Dennoch")  # sentence-initial adverb, not a name
    assert clean_span("Platin")
    assert clean_span("1871")
    assert clean_span("die offene Gesellschaft")


def test_negation_rules() -> None:
    ref = "Die Stadt, die vor Richmond Hauptstadt von Virginia war, ist Williamsburg."
    assert not negation_ok(
        ref, "Die Stadt, die vor Richmond Hauptstadt von Virginia war nicht, ist Williamsburg."
    )
    assert negation_ok("Die Frist ist verlängert.", "Die Frist ist nicht verlängert.")
    assert not negation_ok("Der Wert ist hoch.", "Der Wert ist hoch nicht.")
    orient = "Sie kommt nicht von einem Faktor, sondern entwickelt sich."
    assert not negation_ok(orient, "Sie kommt von einem Faktor, sondern entwickelt sich.")
