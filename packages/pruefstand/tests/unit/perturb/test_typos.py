"""typos: one seeded QWERTZ-style edit in a word of six or more letters (T4.4)."""

import re

import numpy as np
import pytest

from pruefstand.perturb.typos import QWERTZ_NEIGHBOURS, Typos

P = Typos()
QUESTION = "Was ist die Kündigungsfrist?"


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance (insert, delete, substitute, adjacent transposition)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def words(text: str) -> list[str]:
    return text.split(" ")


def test_exactly_one_word_differs_by_one_edit() -> None:
    result = P.apply(QUESTION, np.random.default_rng(1))
    assert result.changed
    before, after = words(QUESTION), words(result.text)
    assert len(before) == len(after)
    diff = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert len(diff) == 1
    assert edit_distance(*diff[0]) == 1
    assert diff[0][0].rstrip("?") == "Kündigungsfrist"


def test_same_seed_same_output() -> None:
    for seed in range(20):
        a = P.apply(QUESTION, np.random.default_rng(seed))
        b = P.apply(QUESTION, np.random.default_rng(seed))
        assert a == b


def test_seeds_give_different_edits() -> None:
    outputs = {P.apply(QUESTION, np.random.default_rng(s)).text for s in range(40)}
    assert len(outputs) > 3


def test_rng_is_the_only_source_of_randomness() -> None:
    rng = np.random.default_rng(5)
    first = P.apply(QUESTION, rng)
    second = P.apply(QUESTION, rng)
    assert first.changed
    assert second.changed


@pytest.mark.parametrize(
    "text",
    [
        "Gilt § 622 BGB bei 1.000,50 € ab 03.10.2026?",
        "Gilt KSchG, GmbHG, ArbSchG und DSGVO?",
        "Wie lang ist 12 Tage?",
        "Ist das so?",
    ],
)
def test_protected_tokens_and_short_words_unchanged(text: str) -> None:
    for seed in range(30):
        result = P.apply(text, np.random.default_rng(seed))
        assert not result.changed
        assert result.text == text


def test_protected_tokens_survive_next_to_a_typo() -> None:
    text = "Gilt § 622 BGB für die Kündigungsfrist ab 03.10.2026 und 1.000,50 €?"
    for seed in range(60):
        out = P.apply(text, np.random.default_rng(seed)).text
        for token in ("§ 622 BGB", "03.10.2026", "1.000,50 €"):
            assert token in out
        assert len(re.findall(r"\bBGB\b", out)) == 1


def test_substitution_uses_neighbouring_keys() -> None:
    assert "w" in QWERTZ_NEIGHBOURS["q"]
    assert "z" in QWERTZ_NEIGHBOURS["t"]
    assert "y" in QWERTZ_NEIGHBOURS["x"]
    assert all(k not in v for k, v in QWERTZ_NEIGHBOURS.items())


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("typos", False)


def test_overlong_letter_run_is_not_a_word() -> None:
    text = "a" * 100_000
    result = P.apply(text, np.random.default_rng(0))
    assert not result.changed
    assert result.text == text


@pytest.mark.parametrize(
    "text",
    [
        "Siehe https://www.gesetze-im-internet.de/bgb",
        "Schreiben Sie an kontakt@beispielfirma.de",
        "Siehe www.beispielfirma.de",
        "Siehe gesetze-im-internet.de",
        "Das Token CANARY-XX-abcdef erscheint",
        "Das Token canary_token-0123abcdef erscheint",
    ],
)
def test_urls_emails_and_canaries_are_never_edited(text: str) -> None:
    for seed in range(40):
        assert not P.apply(text, np.random.default_rng(seed)).changed


def test_words_next_to_a_url_are_still_eligible() -> None:
    text = "Kündigungsfrist siehe https://www.gesetze-im-internet.de/bgb"
    out = {P.apply(text, np.random.default_rng(s)).text for s in range(30)}
    assert all(o.endswith("https://www.gesetze-im-internet.de/bgb") for o in out)
    assert all(o != text for o in out)


def test_every_eligible_word_gets_picked() -> None:
    text = "Kündigungsfrist Probezeit Arbeitnehmer Vergütung"
    hit = set()
    for seed in range(120):
        out = P.apply(text, np.random.default_rng(seed)).text.split(" ")
        hit |= {i for i, (a, b) in enumerate(zip(text.split(" "), out, strict=True)) if a != b}
    assert hit == {0, 1, 2, 3}


def test_first_letter_is_never_edited() -> None:
    text = "Kündigungsfrist Probezeit Arbeitnehmer Vergütung"
    for seed in range(200):
        out = P.apply(text, np.random.default_rng(seed)).text.split(" ")
        assert [w[0] for w in out] == [w[0] for w in text.split(" ")]


def test_all_three_edit_kinds_occur() -> None:
    kinds = {P.apply(QUESTION, np.random.default_rng(s)).notes.split(":")[0] for s in range(60)}
    assert kinds == {"deletion", "transposition", "substitution"}


def test_written_out_law_name_in_lowercase_is_skipped() -> None:
    for text in ("gewerbeordnung", "Gewerbeordnung", "Kündigungsschutzgesetz"):
        for seed in range(30):
            assert not P.apply(text, np.random.default_rng(seed)).changed
