"""Qualifier forms, law lending, range cap, linear-time bound and multi-word laws (T1.5a)."""

import time
from collections.abc import Iterator

import pytest

from pruefstand.core.citations import (
    Citation,
    aliases,
    extract_citations,
    normalise,
    parse_one,
)
from pruefstand.core.citations.aliases import LawAliases


def _c(text: str) -> Citation:
    c = parse_one(text)
    assert c is not None, text
    return c


def _norm(text: str) -> list[str]:
    return [normalise(c) for c in extract_citations(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Art. 6 Abs. 1 lit. a und b DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("Art. 6 Abs. 1 lit. a–f DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("Art. 6 Abs. 1 lit. a bis c DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("Art. 6 Abs. 1 lit. f) DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("Art. 6 Abs. 1 UAbs. 2 DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("Art. 6 Abs. 1 Unterabs. 2 DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("§ 1 Abs. 2 Halbsatz 2 KSchG", ["§ 1 Abs. 2 KSchG"]),
        ("§ 1 Abs. 2 Hs. 2 KSchG", ["§ 1 Abs. 2 KSchG"]),
        ("§ 1 Abs. 2 Alt. 1 KSchG", ["§ 1 Abs. 2 KSchG"]),
        ("§ 1 Abs. 2 Var. 1 KSchG", ["§ 1 Abs. 2 KSchG"]),
        ("Art. 17 und 18 DSGVO", ["Art. 17 DSGVO", "Art. 18 DSGVO"]),
        ("Section 1 and 2 BGB", ["§ 1 BGB", "§ 2 BGB"]),
        ("§ 1 Abs. (2) KSchG", ["§ 1 Abs. 2 KSchG"]),
        ("ART. 6 ABS. 1 LIT. f DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
        ("PARAGRAPH 622 BGB", ["§ 622 BGB"]),
        ("Art. 6 DSGVO-konform", ["Art. 6 DSGVO"]),
        ("§ 705 BGB-Gesellschaft", ["§ 705 BGB"]),
    ],
)
def test_tolerated_qualifier_forms(text: str, expected: list[str]) -> None:
    assert _norm(text) == expected


def test_full_granularity_keeps_first_lit_of_a_list() -> None:
    (c,) = extract_citations("Art. 6 Abs. 1 lit. a und b DSGVO")
    assert normalise(c, "full") == "Art. 6 Abs. 1 lit. a DSGVO"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "§ 280 Abs. 1 i.V.m. § 241 Abs. 2 und § 311 BGB",
            ["§ 280 Abs. 1 BGB", "§ 241 Abs. 2 BGB", "§ 311 BGB"],
        ),
        ("§ 1 und § 2 BGB", ["§ 1 BGB", "§ 2 BGB"]),
        ("§ 1, § 2 sowie § 3 BGB", ["§ 1 BGB", "§ 2 BGB", "§ 3 BGB"]),
        ("Art. 5 und Art. 6 DSGVO", ["Art. 5 DSGVO", "Art. 6 DSGVO"]),
        ("§ 622 Abs. 2 i.V.m. Art. 6 DSGVO", ["Art. 6 DSGVO"]),
        ("§ 622 und Art. 6 DSGVO", ["Art. 6 DSGVO"]),
        ("§ 1 AI Act", []),
        ("§ 6 DSGVO", []),
        ("§ 6 DSGVO und § 7 BGB", ["§ 7 BGB"]),
        ("Art. 1 GG und Art. 20 GG", ["Art. 1 GG", "Art. 20 GG"]),
        ("§ 1 BGB und KSchG", ["§ 1 BGB"]),
        ("Art. 6 i.V.m. § 280 BGB", ["§ 280 BGB"]),
        ("Art. 5 Abs. 1 lit. a i.V.m. § 280 BGB", ["§ 280 BGB"]),
        ("§ 5 i.V.m. Art. 1 GG", ["Art. 1 GG"]),
        ("§ 1 und Art. 3 GG", ["Art. 3 GG"]),
        ("§ 1 und § 5 DSGVO. Art. 3 GG", ["Art. 3 GG"]),
    ],
)
def test_law_lending(text: str, expected: list[str]) -> None:
    assert _norm(text) == expected


@pytest.mark.parametrize(
    ("text", "count"),
    [("§§ 1 bis 50 BGB", 50), ("§§ 1 bis 51 BGB", 2), ("§§ 1 bis 1000 BGB", 2)],
)
def test_range_cap(text: str, count: int) -> None:
    assert len(extract_citations(text)) == count


def test_over_cap_range_keeps_both_ends() -> None:
    assert _norm("§§ 1 bis 1000 BGB") == ["§ 1 BGB", "§ 1000 BGB"]


# Scaling check, not a wall-clock bound: a 4x larger input must cost at most _MAX_RATIO x the base
# input. The cost is the CPU time of this process (`process_time`, so other processes sharing the
# machine do not count), min-of-N, with the small and the big input measured alternately so that
# drift cancels out. Linear is ~4x, the original quadratic bug ~16x, so 10x separates them with
# margin on both sides. The absolute bound is only a hang guard.
_SCALE = 4
_MAX_RATIO = 10.0
_HANG_GUARD_S = 120.0
_REPS = 5


def _cpu_time(text: str) -> float:
    start = time.process_time()
    extract_citations(text)
    return time.process_time() - start


def _assert_scales_linearly(unit: str, count: int) -> None:
    small_text, big_text = unit * count, unit * count * _SCALE
    small = big = float("inf")
    for _ in range(_REPS):
        small = min(small, _cpu_time(small_text))
        big = min(big, _cpu_time(big_text))
    assert big < _HANG_GUARD_S
    assert big <= _MAX_RATIO * max(small, 1e-3), f"{_SCALE}x input took {big / small:.1f}x"


@pytest.mark.parametrize(
    ("unit", "count"),
    [
        ("s. 1 ", 5000),
        ("Sec. 1 s. 1 ", 2500),
        ("§ 1 Abs. 1 ", 5000),
        ("§ 1 und ", 5000),
        ("§ 1 i.V.m. ", 5000),
        ("s. 1 Abs. 1 Sec. 2 § 3 Art. 4 ", 1250),
    ],
)
def test_runs_in_linear_time(unit: str, count: int) -> None:
    _assert_scales_linearly(unit, count)


@pytest.fixture
def sgb_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    table = LawAliases(version=1, national={"SGB IV": ("Sozialgesetzbuch Viertes Buch",)}, eu={})
    monkeypatch.setattr(aliases, "law_aliases", lambda: table)
    aliases._law_regex.cache_clear()
    aliases._lookup.cache_clear()
    yield
    monkeypatch.undo()
    aliases._law_regex.cache_clear()
    aliases._lookup.cache_clear()


@pytest.mark.usefixtures("sgb_table")
def test_multi_word_abbreviation_parses() -> None:
    assert _norm("§ 7 SGB IV") == ["§ 7 SGB IV"]
    assert _norm("§ 7 Abs. 1 Sozialgesetzbuch  Viertes Buch") == ["§ 7 Abs. 1 SGB IV"]
    assert parse_one(normalise(_c("§ 7 SGB IV"))) == _c("§ 7 SGB IV")


def test_output_is_capped_against_amplification() -> None:
    text = "§§ 1 bis 50 BGB " * 6000
    found = extract_citations(text)
    assert len(found) == max(100, len(text) // 20)
    assert [c.number for c in found[:2]] == ["1", "2"]  # the excess is dropped in order


def test_amplification_input_scales_linearly() -> None:
    _assert_scales_linearly("§§ 1 bis 50 BGB ", 500)


def test_short_text_keeps_the_floor_of_100() -> None:
    assert (
        len(extract_citations("§§ 1 bis 50 BGB und §§ 60 bis 109 BGB und §§ 200 bis 249 BGB"))
        == 100
    )
