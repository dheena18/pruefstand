"""T5.3 S3: the deterministic edits (real German inputs, no model)."""

from pathlib import Path

import numpy as np
import pytest
from rq2.calib_sources import load_germanquad
from rq2.construct import (
    FRAMES,
    REFUSALS,
    frame,
    hedge,
    negate,
    partial,
    same_paragraph_span,
    swap_first_number,
    token_jaccard,
)

from pruefstand.metrics.deterministic.refusal import is_refusal

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1990", "1991"),
        ("vier Wochen", "fünf Wochen"),
        ("am 3. Oktober 1990", "am 4. Oktober 1990"),
        ("zwölf Monate", "dreizehn Monate"),
        ("Berlin", None),
        ("sieben Millionen", "acht Millionen"),
        ("Vier Tage", "Fünf Tage"),
        ("am 31. Mai 373", "am 30. Mai 373"),
        ("9 Jahre", "8 Jahre"),
        ("die zweiten 3 Tage", "die zweiten 4 Tage"),
    ],
)
def test_swap_first_number(text: str, expected: str | None) -> None:
    assert swap_first_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Die Frist ist verlängert.", "Die Frist ist nicht verlängert."),
        ("Das ist nicht erlaubt.", "Das ist erlaubt."),
        ("Berlin", None),
        ("Er hat keine Erlaubnis.", "Er hat eine Erlaubnis."),
        (
            "Der Antrag muss schriftlich gestellt werden.",
            "Der Antrag muss nicht schriftlich gestellt werden.",
        ),
    ],
)
def test_negate(text: str, expected: str | None) -> None:
    assert negate(text) == expected


def test_partial() -> None:
    assert partial("Kündigungsfrist und Probezeit") == "Kündigungsfrist"
    assert partial("Patriarch von Alexandria und Kirchenvater.") == "Patriarch von Alexandria"
    assert (
        partial("die Ernennung durch den Bundespräsidenten nach der Wahl")
        == "die Ernennung durch den"
    )
    assert partial("Berlin") is None


def test_token_jaccard() -> None:
    assert token_jaccard("der Bundestag", "Bundestag") == 0.5
    assert token_jaccard("Bundestag", "Bundesrat") == 0.0


def test_frame_is_one_of_four_and_deterministic() -> None:
    first = frame("1871", seed=0)
    assert first == frame("1871", seed=0)
    assert first in {f.format(a="1871") for f in FRAMES}
    assert len({frame("1871", seed=s) for s in range(40)}) == 4


def test_same_paragraph_span_never_overlaps_an_answer() -> None:
    rows = load_germanquad(FIXTURES / "germanquad_test_6.jsonl")
    for row in rows:
        spans = [(s, s + len(t)) for t, s in row.answers]
        for seed in range(25):
            span = same_paragraph_span(
                row.context, row.answers, row.answers[0][0], np.random.default_rng(seed)
            )
            assert span is not None
            pos = row.context.find(span)
            assert pos >= 0
            assert not any(pos < end and start < pos + len(span) for start, end in spans)
            assert all(
                span.casefold() not in t.casefold() and t.casefold() not in span.casefold()
                for t, _ in row.answers
            )


def test_refusal_paraphrases_at_most_two_canonical() -> None:
    assert len(REFUSALS) == 6
    assert sum(is_refusal(r) for r in REFUSALS) <= 2


def test_hedge_keeps_the_answer() -> None:
    answer = "Rotes Licht wird im Wasser am stärksten absorbiert."
    assert (
        hedge(answer, 0)
        == "Soweit ersichtlich: Rotes Licht wird im Wasser am stärksten absorbiert."
    )
    assert (
        hedge(answer, 1)
        == "Nach den Dokumenten gilt: Rotes Licht wird im Wasser am stärksten absorbiert."
    )
    assert not any(is_refusal(hedge(answer, i)) for i in range(2))
