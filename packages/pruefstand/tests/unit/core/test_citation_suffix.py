"""One- and two-letter section suffixes (`§ 53ca KWG`) and their guards (T1.5a follow-up)."""

from collections.abc import Iterator

import pytest
from testsupport.timing import assert_scales_linearly

from pruefstand.core.citations import (
    Citation,
    aliases,
    citations_match,
    extract_citations,
    normalise,
)
from pruefstand.core.citations.aliases import LawAliases, law_aliases


@pytest.fixture(autouse=True)
def _kwg_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The committed table without KWG (T2.2 appends it); the suffix tests need that law."""
    base = law_aliases()
    table = LawAliases(
        version=base.version, national={**base.national, "KWG": ("Kreditwesengesetz",)}, eu=base.eu
    )
    monkeypatch.setattr(aliases, "law_aliases", lambda: table)
    aliases._law_regex.cache_clear()
    aliases._lookup.cache_clear()
    yield
    monkeypatch.undo()
    aliases._law_regex.cache_clear()
    aliases._lookup.cache_clear()


def _norm(text: str) -> list[str]:
    return [normalise(c) for c in extract_citations(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 53ca KWG", ["§ 53ca KWG"]),
        ("§ 53cq KWG", ["§ 53cq KWG"]),
        ("§ 612a BGB", ["§ 612a BGB"]),
        ("§ 5a UWG", ["§ 5a UWG"]),
        ("§53ca KWG", ["§ 53ca KWG"]),
        ("§ 53ca Abs. 1 Satz 2 KWG", ["§ 53ca Abs. 1 KWG"]),
        ("§§ 53c bis 53cq KWG", ["§ 53c KWG", "§ 53cq KWG"]),
        ("§§ 53ca, 53cb KWG", ["§ 53ca KWG", "§ 53cb KWG"]),
        ("Art. 12ab DSGVO", ["Art. 12ab DSGVO"]),
    ],
)
def test_two_letter_suffix_is_part_of_the_number(text: str, expected: list[str]) -> None:
    assert _norm(text) == expected


def test_number_is_stored_with_its_suffix() -> None:
    (c,) = extract_citations("§ 53ca KWG")
    assert (c.kind, c.number, c.law) == ("para", "53ca", "KWG")
    assert citations_match(c, Citation(kind="para", number="53ca", law="KWG")) is True
    assert citations_match(c, Citation(kind="para", number="53c", law="KWG")) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 305ff. BGB", ["§ 305 BGB"]),
        ("§ 305ff BGB", []),
        ("§§ 305 ff. BGB", ["§ 305 BGB"]),
        ("§ 305f. BGB", ["§ 305 BGB"]),
        ("§ 305f BGB", ["§ 305f BGB"]),
    ],
)
def test_ff_is_never_a_suffix(text: str, expected: list[str]) -> None:
    assert _norm(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 5abc BGB", []),
        ("§ 622BGB", ["§ 622 BGB"]),
        ("§ 622Bgb", ["§ 622 BGB"]),
        ("§ 1 und 2 BGB", ["§ 1 BGB", "§ 2 BGB"]),
        ("§ 12 bis 14 BGB", ["§ 12 BGB", "§ 13 BGB", "§ 14 BGB"]),
        ("§ 7 so BGB", []),
        ("§ 5 in BGB", []),
        ("§ 5in BGB", []),
        ("Art. 6in DSGVO", []),
        ("§ 6im BGB", []),
    ],
)
def test_prose_never_becomes_a_suffix(text: str, expected: list[str]) -> None:
    assert _norm(text) == expected


@pytest.mark.parametrize(
    ("unit", "count"), [("§ 1ab ", 20000), ("§ 5a", 20000), ("§ 53ca KWG ", 5000)]
)
def test_suffix_scan_is_linear(unit: str, count: int) -> None:
    small, big = unit * (count // 4), unit * count
    assert_scales_linearly(
        lambda: extract_citations(small), lambda: extract_citations(big), scale=4
    )


@pytest.mark.parametrize(
    "text",
    ["§ 5abAbs. 2 BGB", "§ 5abc Abs. 2 BGB", "§ 5abc und 6 BGB", "§ 5abund 6 BGB"],
)
def test_suffix_must_end_at_a_word_boundary(text: str) -> None:
    """A longer word after the digits is no suffix (else 5ab would match)."""
    assert all(c.number != "5ab" for c in extract_citations(text))
    assert _norm(text) == []


@pytest.mark.parametrize(
    ("text", "expected"), [("§ 5te BGB", ["§ 5te BGB"]), ("§ 3to BGB", ["§ 3to BGB"])]
)
def test_known_false_positives_are_a_conscious_limit(text: str, expected: list[str]) -> None:
    """Prose like `§ 5te` (fünfte) reads as a suffix: only a deny-list of function words guards.

    Recorded on purpose so a future tightening (or loosening) of the heuristic is deliberate.
    """
    assert _norm(text) == expected


@pytest.mark.parametrize(("text", "number"), [("§ 5am BGB", "5"), ("§ 5an BGB", "5")])
def test_am_an_are_knowingly_excluded(text: str, number: str) -> None:
    """`am`/`an` are real CRR suffixes (Art. 325am) but excluded as prose; revisit with T2.4."""
    assert [c.number for c in extract_citations(text)] == []
