"""T5.4b: sentence answers for the ``negate`` cell (real GermanQuAD rows, no model)."""

from pathlib import Path

import pytest
from rq2.calib_schema import CalibrationItem, make_item_id
from rq2.calib_sources import QuadRow, load_germanquad
from rq2.make_degraded import make_pairs
from rq2.sentence_answers import answer_sentence, match_row, negated_sentence

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def quad() -> dict[str, QuadRow]:
    return {r.qid: r for r in load_germanquad(FIXTURES / "germanquad_test_6.jsonl")}


def _positive(row: QuadRow, answer: str) -> CalibrationItem:
    inputs = {"frage": row.question, "referenz": row.answers[0][0], "antwort": answer}
    cluster = "germanquad:" + row.article
    return CalibrationItem(
        item_id=make_item_id("correctness", cluster, "annotator_answer_2", inputs),
        metric="answer_correctness",
        cluster_id=cluster,
        inputs=inputs,
        label=2,
        source="germanquad",
        construction="annotator_answer_2",
        calib_split="test",
    )


def test_the_source_sentence_of_the_answer_is_negated(quad: dict[str, QuadRow]) -> None:
    row = quad["38630"]
    assert answer_sentence(row, "Die Ehe wurde heilig gehalten") == (
        "Die Ehe wurde heilig gehalten, es herrschte ursprünglich Monogamie."
    )
    assert negated_sentence(row, "Die Ehe wurde heilig gehalten") == (
        "Die Ehe wurde heilig gehalten, es herrschte ursprünglich Monogamie.",
        "Die Ehe wurde nicht heilig gehalten, es herrschte ursprünglich Monogamie.",
    )


def test_sentences_without_a_listed_verb_or_with_broken_splits_are_skipped(
    quad: dict[str, QuadRow],
) -> None:
    # "kümmert sich ... gestattet": no verb of FINITE_VERBS, so no negation
    assert negated_sentence(quad["36705"], "rund sieben Millionen") is None
    # a bad split ("Mai 373 ebenda) war ...") has an unbalanced bracket
    assert answer_sentence(quad["38463"], "Patriarch von Alexandria und Kirchenvater") is None
    # a multi-sentence answer lies in no single sentence
    row = quad["41192"]
    assert answer_sentence(row, row.answers[1][0]) is None


def test_the_answer_must_start_in_the_first_clause(quad: dict[str, QuadRow]) -> None:
    # "Monogamie" follows the comma: negating "wurde" would not negate it
    assert negated_sentence(quad["38630"], "ursprünglich Monogamie") is None


def test_a_negation_after_the_answer_is_refused(quad: dict[str, QuadRow]) -> None:
    # "Die Ehe" ends before "wurde nicht": the edit negates the predicate, not the answer span
    assert negated_sentence(quad["38630"], "Die Ehe") is None
    # an edit inside the span is kept
    assert negated_sentence(quad["38630"], "Die Ehe wurde heilig gehalten") is not None


def test_items_are_matched_to_their_germanquad_row(quad: dict[str, QuadRow]) -> None:
    row = quad["38630"]
    item = _positive(row, "Die Ehe wurde heilig gehalten")
    assert match_row(item, list(quad.values())) == row
    other = item.model_copy(update={"inputs": {**item.inputs, "referenz": "anders"}})
    assert match_row(other, list(quad.values())) is None


def test_sentence_pairs_fill_the_negate_cell_after_the_span_pairs(
    quad: dict[str, QuadRow],
) -> None:
    rows = list(quad.values())
    span = _positive(quad["38630"], "Die Ehe wurde heilig gehalten")  # the span itself negates
    sentence = _positive(quad["38630"], "heilig gehalten")  # no verb: only its sentence negates
    swap_only = _positive(quad["36705"], "rund sieben Millionen")
    items = [span, sentence, swap_only]
    pairs = make_pairs(items, "correctness", seed=1234, quad_rows=rows)
    negates = [p for p in pairs if p["edit"] == "negate"]
    assert [p["form"] for p in negates] == ["span", "sentence"]
    by_form = {p["form"]: p for p in negates}
    assert by_form["span"]["base_item_id"] == span.item_id
    assert by_form["sentence"]["pair_id"] == f"{sentence.item_id}:negate_sentence"
    base, worse = by_form["sentence"]["inputs"], by_form["sentence"]["degraded"]
    assert isinstance(base, dict)
    assert isinstance(worse, dict)
    assert base["antwort"] == "Die Ehe wurde heilig gehalten, es herrschte ursprünglich Monogamie."
    assert str(worse["antwort"]).startswith("Die Ehe wurde nicht heilig")
    assert base["referenz"] == span.inputs["referenz"]
    assert make_pairs(items, "correctness", seed=1234, quad_rows=rows) == pairs
    # without the source rows the cell has the span pairs only (the T5.4 behaviour)
    plain = make_pairs(items, "correctness", seed=1234)
    assert [p["form"] for p in plain if p["edit"] == "negate"] == ["span"]


def test_the_cell_size_and_one_sentence_per_question(quad: dict[str, QuadRow]) -> None:
    rows = list(quad.values())
    span = _positive(quad["38630"], "Die Ehe wurde heilig gehalten")
    first = _positive(quad["38630"], "heilig gehalten")
    second = _positive(quad["38630"], "heilig")  # same question, same sentence: skipped
    full = make_pairs([first, second], "correctness", seed=1234, quad_rows=rows)
    assert len([p for p in full if p["edit"] == "negate"]) == 1
    capped = make_pairs([span, first], "correctness", seed=1234, per_edit=1, quad_rows=rows)
    assert [p["form"] for p in capped if p["edit"] == "negate"] == ["span"]
