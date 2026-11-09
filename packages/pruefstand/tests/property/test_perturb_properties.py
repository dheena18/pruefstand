"""Property and timing tests for the deterministic perturbations (T4.4)."""

import unicodedata
from collections.abc import Callable

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from testsupport.timing import assert_scales_linearly

from pruefstand.core.citations import extract_citations
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


def _applier(name: str, text: str) -> Callable[[], object]:
    p = get_perturbation(name)
    return lambda: p.apply(text, np.random.default_rng(0))


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
    """4x the input must not cost much more than 4x the CPU time (ratio, not absolute)."""
    for name, build in ADVERSARIAL.items():
        small, large = _applier(name, build(20_000)), _applier(name, build(80_000))
        small()  # warm up caches (law regex compile)
        assert_scales_linearly(small, large, scale=4, floor_s=1e-4, reps=3)


URL = "https://www.example.org/pfad/seite?a=b"
CITATIONS = "§ 622 Abs. 2 BGB und Art. 6 DSGVO"
SAFE_WORDS = st.lists(
    st.sampled_from(
        ["Kündigungsfrist", "Frage", "Gebühren", "gilt", "bei", "Probezeit", "ggf.", "z. B."]
    ),
    max_size=8,
).map(" ".join)


@given(SAFE_WORDS, SAFE_WORDS, st.integers(0, 1000))
def test_urls_and_citations_survive_the_text_perturbations(
    before: str, after: str, seed: int
) -> None:
    """A URL stays byte for byte; the citations of the text parse to the same list."""
    text = f"{before} {URL} {CITATIONS} {after}"
    wanted = extract_citations(text)
    for name in ("typos", "umlaut_translit", "eszett", "numbers", "dates", "abbreviations"):
        out = get_perturbation(name).apply(text, np.random.default_rng(seed)).text
        assert URL in out, name
        assert extract_citations(out) == wanted, name
