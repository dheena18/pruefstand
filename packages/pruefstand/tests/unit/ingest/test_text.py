"""Shared text helpers (T2.2): token counting, NFC, whitespace, hyphenation, linear time."""

import time
import unicodedata
from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pruefstand.ingest.text import (
    count_tokens,
    join_hyphenation,
    nfc,
    normalise_text,
    normalise_whitespace,
)


def test_count_tokens_prompt_example() -> None:
    assert count_tokens("§ 622 Abs. 2 BGB.") == 7


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("   \n\t", 0), ("Kündigungsfrist", 1), ("a,b", 3), ("(1) Das Arbeitsverhältnis", 5)],
)
def test_count_tokens_table(text: str, expected: int) -> None:
    assert count_tokens(text) == expected


def test_nfc_composes_decomposed_umlauts() -> None:
    decomposed = "Kündigung"
    assert decomposed != "Kündigung"
    assert nfc(decomposed) == "Kündigung"
    assert unicodedata.is_normalized("NFC", nfc(decomposed))


def test_normalise_whitespace_collapses_runs_and_keeps_lines() -> None:
    raw = "  (1)  Das   Arbeitsverhältnis\t\tendet. \r\n\r\n\n (2)   Zweiter Absatz  \n"
    assert normalise_whitespace(raw) == "(1) Das Arbeitsverhältnis endet.\n(2) Zweiter Absatz"


def test_normalise_text_is_nfc_and_whitespace_clean() -> None:
    out = normalise_text("  Kündigung   und\n\n  Frist ")
    assert out == "Kündigung und\nFrist"


def test_join_hyphenation_joins_line_break_hyphens_only() -> None:
    assert join_hyphenation("Kündi-\ngung der Arbeits-\nverhältnisse") == (
        "Kündigung der Arbeitsverhältnisse"
    )
    assert join_hyphenation("Ost-\nWest und E-Mail und 1-\n2") == "Ost-\nWest und E-Mail und 1-\n2"
    assert join_hyphenation("Rand-") == "Rand-"


@given(st.text())
def test_normalise_text_is_idempotent_and_nfc(text: str) -> None:
    once = normalise_text(text)
    assert normalise_text(once) == once
    assert unicodedata.is_normalized("NFC", once)


@given(st.text())
def test_count_tokens_is_additive_over_blank_separated_parts(text: str) -> None:
    assert count_tokens(text + "\n\n" + text) == 2 * count_tokens(text)


def _seconds(func: Callable[[str], object], text: str) -> float:
    start = time.perf_counter()
    func(text)
    return time.perf_counter() - start


@pytest.mark.parametrize(
    "unit", ["a ", "\n", "(((", "  \t", "-\n", "̈", "x" * 40 + " ", "§ 1 ", "ä-\nb "]
)
@pytest.mark.parametrize("func", [count_tokens, normalise_text, join_hyphenation])
def test_helpers_run_in_linear_time(func: Callable[[str], object], unit: str) -> None:
    small, large = unit * 20_000, unit * 160_000
    t_small = min(_seconds(func, small) for _ in range(3))
    t_large = min(_seconds(func, large) for _ in range(3))
    assert t_large < 2.0
    assert t_large < 8 * 6 * max(t_small, 0.002)  # 8x the input: allow 6x the linear ratio


@settings(deadline=2000, max_examples=25, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.sampled_from(["a ", "\n", "(((", "\u00a0 \t", "-\n", "\u0308", "x" * 40 + " ", "ä-\nb "]),
    st.integers(min_value=10_000, max_value=100_000),
)
def test_helpers_time_bound_on_generated_pathological_text(unit: str, repeat: int) -> None:
    text = unit * repeat
    count_tokens(text)
    normalise_text(text)
    join_hyphenation(text)
