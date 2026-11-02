"""Property and timing tests for the deterministic perturbations (T4.4)."""

import time
import unicodedata
from collections.abc import Callable

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from pruefstand.perturb.registry import get_perturbation, perturbation_names

ALPHABET = "abcdefghijklmnopqrstuvwxyzäöüßABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜẞ0123456789 .,;:?§€%-()/"
german = st.text(alphabet=ALPHABET, max_size=200)
anything = st.text(max_size=200)


@given(anything, st.integers(0, 2**32 - 1))
def test_never_raises_and_output_is_nfc(text: str, seed: int) -> None:
    for name in perturbation_names():
        result = get_perturbation(name).apply(text, np.random.default_rng(seed))
        assert unicodedata.is_normalized("NFC", result.text)
        assert result.changed == (result.text != unicodedata.normalize("NFC", text))


@given(german)
def test_umlaut_translit_leaves_no_umlaut(text: str) -> None:
    out = get_perturbation("umlaut_translit").apply(text, np.random.default_rng(0)).text
    assert not any(c in out for c in "äöüÄÖÜ")


@given(german)
def test_eszett_is_idempotent(text: str) -> None:
    p = get_perturbation("eszett")
    once = p.apply(text, np.random.default_rng(0))
    twice = p.apply(once.text, np.random.default_rng(0))
    assert twice.text == once.text
    assert not twice.changed
    assert "ß" not in once.text


@given(german)
def test_deterministic_perturbations_are_idempotent_or_stable(text: str) -> None:
    for name in ("umlaut_translit", "eszett", "dates", "abbreviations"):
        p = get_perturbation(name)
        once = p.apply(text, np.random.default_rng(0)).text
        assert p.apply(once, np.random.default_rng(0)).text == once


@given(german, st.integers(0, 1000))
def test_typos_change_at_most_one_word_and_keep_digits(text: str, seed: int) -> None:
    out = get_perturbation("typos").apply(text, np.random.default_rng(seed)).text
    assert [c for c in out if c.isdigit() or c in "§€%"] == [
        c for c in text if c.isdigit() or c in "§€%"
    ]
    before, after = text.split(" "), out.split(" ")
    assert len(before) == len(after)
    assert sum(a != b for a, b in zip(before, after, strict=True)) <= 1


@given(german, st.integers(0, 1000))
def test_same_seed_same_result(text: str, seed: int) -> None:
    for name in perturbation_names():
        p = get_perturbation(name)
        assert p.apply(text, np.random.default_rng(seed)) == p.apply(
            text, np.random.default_rng(seed)
        )


def _seconds(name: str, text: str) -> float:
    p = get_perturbation(name)
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        p.apply(text, np.random.default_rng(0))
        best = min(best, time.perf_counter() - start)
    return best


ADVERSARIAL: dict[str, Callable[[int], str]] = {
    "umlaut_translit": lambda n: "äöü" * n,
    "eszett": lambda n: "ß" * n,
    "numbers": lambda n: "1" + ".111" * n + "x",
    "dates": lambda n: "1.1" * n,
    "citation_style": lambda n: "§ 1 " * n,
    "abbreviations": lambda n: "i. V. " * n,
    "typos": lambda n: "Kündigungsfrist " * n,
}


def test_linear_time_on_adversarial_input() -> None:
    """Doubling the input must not much more than double the time (ratio, not absolute)."""
    for name, build in ADVERSARIAL.items():
        small, large = build(20_000), build(40_000)
        _seconds(name, small)  # warm up caches (law regex compile)
        ratio = _seconds(name, large) / max(_seconds(name, small), 1e-4)
        assert ratio < 4.0, (name, ratio)
