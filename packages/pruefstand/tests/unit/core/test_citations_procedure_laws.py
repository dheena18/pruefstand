"""Procedure and tax laws the OLDP citation graph cites (T2.3a)."""

import pytest

from pruefstand.core.citations import extract_citations, normalise, parse_one
from pruefstand.core.citations.aliases import is_national, resolve_law


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 519 ZPO", "§ 519 ZPO"),
        ("§ 42 Abs. 2 VwGO", "§ 42 Abs. 2 VwGO"),
        ("§ 144 SGG", "§ 144 SGG"),
        ("§ 19 EStG", "§ 19 EStG"),
        ("§ 519 der Zivilprozessordnung", "§ 519 ZPO"),
        ("§ 19 des Einkommensteuergesetzes", "§ 19 EStG"),
        ("Section 144 of the Social Courts Act", "§ 144 SGG"),
    ],
)
def test_procedure_and_tax_laws_parse(text: str, expected: str) -> None:
    citation = parse_one(text)
    assert citation is not None
    assert normalise(citation) == expected
    assert [normalise(c) for c in extract_citations(text)] == [expected]


def test_the_laws_are_national() -> None:
    for law in ("ZPO", "VwGO", "SGG", "EStG"):
        assert is_national(law)
        assert resolve_law(law) == law
