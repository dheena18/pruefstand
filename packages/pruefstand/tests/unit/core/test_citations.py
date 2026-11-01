"""Citation parser, normaliser, matching rule and credit rule (T1.5a)."""

import logging
import unicodedata

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pruefstand.core.citations import (
    Citation,
    aliases,
    citation_credit,
    citations_match,
    extract_citations,
    normalise,
    parse_one,
)
from pruefstand.core.citations.aliases import LawAliases, law_aliases, resolve_law
from pruefstand.core.errors import ConfigError

TABLE: list[tuple[str, list[str]]] = [
    ("§ 622 Abs. 2 Nr. 1 BGB", ["§ 622 Abs. 2 BGB"]),
    ("§622 Absatz 2 Satz 1 BGB", ["§ 622 Abs. 2 BGB"]),
    ("Art. 6 Abs. 1 lit. f DSGVO", ["Art. 6 Abs. 1 DSGVO"]),
    ("Article 6(1)(f) GDPR", ["Art. 6 Abs. 1 DSGVO"]),
    ("Artikel 6 DSGVO", ["Art. 6 DSGVO"]),
    ("§§ 622, 623 BGB", ["§ 622 BGB", "§ 623 BGB"]),
    ("§§ 1–3 KSchG", ["§ 1 KSchG", "§ 2 KSchG", "§ 3 KSchG"]),
    ("§ 622 ff. BGB", ["§ 622 BGB"]),
    ("§ 280 i.V.m. § 241 Abs. 2 BGB", ["§ 280 BGB", "§ 241 Abs. 2 BGB"]),
    ("§ 1 KSchG i.V.m. § 622 BGB", ["§ 1 KSchG", "§ 622 BGB"]),
    ("Paragraph 622 des Bürgerlichen Gesetzbuchs", ["§ 622 BGB"]),
    ("§ 5a UWG", ["§ 5a UWG"]),
    ("Art. 21 NIS-2-Richtlinie", ["Art. 21 NIS2-RL"]),
    ("Gebühren 2026", []),
    ("§ 622", []),
    ("Section 622(2) BGB", ["§ 622 Abs. 2 BGB"]),
    ("Sec. 622 BGB", ["§ 622 BGB"]),
    ("s. 622 German Civil Code", ["§ 622 BGB"]),
    ("Section 1 of the Protection Against Unfair Dismissal Act", ["§ 1 KSchG"]),
    ("§ 622 Abs. 2 S. 1 BGB", ["§ 622 Abs. 2 BGB"]),
]


@pytest.mark.parametrize(("text", "expected"), TABLE)
def test_extract_table(text: str, expected: list[str]) -> None:
    assert [normalise(c) for c in extract_citations(text)] == expected


def test_full_granularity_keeps_satz_nummer_lit() -> None:
    (c,) = extract_citations("§ 622 Abs. 2 Nr. 1 BGB")
    assert normalise(c, "full") == "§ 622 Abs. 2 Nr. 1 BGB"
    (c,) = extract_citations("Art. 6 Abs. 1 lit. f DSGVO")
    assert normalise(c, "full") == "Art. 6 Abs. 1 lit. f DSGVO"
    (c,) = extract_citations("§ 622 Abs. 2 S. 1 Nr. 1 BGB")
    assert normalise(c, "full") == "§ 622 Abs. 2 S. 1 Nr. 1 BGB"
    assert (c.satz, c.nummer, c.absatz) == ("1", "1", "2")


def test_german_satz_is_not_a_section_head() -> None:
    assert [normalise(c) for c in extract_citations("§ 622 Abs. 2 s. 1 BGB")] == [
        "§ 622 Abs. 2 BGB"
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Gemäß § 626 Abs. 1 BGB und Art. 6 Abs. 1 DSGVO gilt",
            ["§ 626 Abs. 1 BGB", "Art. 6 Abs. 1 DSGVO"],
        ),
        ("§ 622 BGB", ["§ 622 BGB"]),
        ("§ 622 des Bürgerlichen Gesetzbuches (BGB)", ["§ 622 BGB"]),
        ("Art. 5 GG", ["Art. 5 GG"]),
        ("Art. 5 KI-Verordnung", ["Art. 5 KI-VO"]),
        ("Article 5 of the AI Act", ["Art. 5 KI-VO"]),
        ("Art. 3 Gesetz über digitale Dienste", ["Art. 3 DSA"]),
        ("Article 3 Digital Services Act", ["Art. 3 DSA"]),
        ("Art. 21 NIS 2 Directive", ["Art. 21 NIS2-RL"]),
        ("Section 5 of the Working Hours Act", ["§ 5 ArbZG"]),
        ("Sections 622 and 623 BGB", ["§ 622 BGB", "§ 623 BGB"]),
        ("§§ 622, 623 Abs. 2 BGB", ["§ 622 BGB", "§ 623 Abs. 2 BGB"]),
        ("§ 622 Abs. 2, 3 BGB", ["§ 622 Abs. 2 BGB"]),
        ("§ 622 Abs. 2, S. 1, Nr. 1 BGB", ["§ 622 Abs. 2 BGB"]),
        ("Art. 6 Abs. 1 lit. f i.V.m. Art. 5 DSGVO", ["Art. 6 Abs. 1 DSGVO", "Art. 5 DSGVO"]),
        ("§ 280 iVm § 241 BGB", ["§ 280 BGB", "§ 241 BGB"]),
        ("§ 280 in Verbindung mit § 241 BGB", ["§ 280 BGB", "§ 241 BGB"]),
        ("§ 622 f. BGB", ["§ 622 BGB"]),
        ("§ 3 BGB, § 4", ["§ 3 BGB"]),
        ("Section 5 GDPR", []),
        ("s. 1 Satz", []),
        ("§§ 1–99999 BGB", ["§ 1 BGB", "§ 99999 BGB"]),
        ("§§ 1–999999 BGB", []),
        ("", []),
    ],
)
def test_extract_extra_forms(text: str, expected: list[str]) -> None:
    assert [normalise(c) for c in extract_citations(text)] == expected


def test_decomposed_umlauts_are_normalised() -> None:
    text = unicodedata.normalize("NFD", "Paragraph 622 des Bürgerlichen Gesetzbuchs")
    assert [normalise(c) for c in extract_citations(text)] == ["§ 622 BGB"]


def test_huge_number_does_not_raise() -> None:
    assert extract_citations("§§ 1–" + "9" * 5000 + " BGB") == []


def test_dropped_citation_is_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        assert extract_citations("§ 622") == []
    assert "citation_dropped" in caplog.text


def test_parse_one() -> None:
    assert parse_one("§ 622 BGB und § 623 BGB") is None
    assert parse_one("Gebühren") is None
    assert parse_one("Art. 6 DSGVO") == Citation(kind="art", number="6", law="DSGVO")
    section = parse_one("Section 622 BGB")
    assert section is not None
    assert section.kind == "para"


def _c(text: str) -> Citation:
    c = parse_one(text)
    assert c is not None, text
    return c


def test_citation_model_is_frozen_and_strict() -> None:
    c = _c("§ 622 BGB")
    with pytest.raises(ValidationError, match="bogus"):
        Citation.model_validate({"kind": "para", "number": "1", "law": "BGB", "bogus": "x"})
    assert hash(c) == hash(_c("§ 622 BGB"))  # frozen models are hashable


@pytest.mark.parametrize(
    ("pred", "gold", "match"),
    [
        ("§ 622 Abs. 2 BGB", "§ 622 BGB", True),
        ("§ 622 Abs. 3 BGB", "§ 622 Abs. 2 BGB", False),
        ("Article 6 GDPR", "Art. 6 DSGVO", True),
        ("§ 622 BGB", "§ 622 KSchG", False),
        ("Art. 6 DSGVO", "§ 6 DSGVO", False),
        ("§ 623 BGB", "§ 622 BGB", False),
        ("§ 622 BGB", "§ 622 Abs. 2 BGB", False),
    ],
)
def test_citations_match(pred: str, gold: str, *, match: bool) -> None:
    assert citations_match(_c(pred), _c(gold)) is match


@pytest.mark.parametrize(
    ("pred", "gold", "credit"),
    [
        ("§ 622 Abs. 2 BGB", "§ 622 Abs. 2 BGB", 1.0),
        ("§ 622 BGB", "§ 622 Abs. 2 BGB", 0.5),
        ("§ 622 Abs. 3 BGB", "§ 622 Abs. 2 BGB", 0.0),
        ("§ 622 Abs. 2 BGB", "§ 622 BGB", 1.0),
        ("§ 623 BGB", "§ 622 BGB", 0.0),
        ("§ 622 BGB", "§ 622 KSchG", 0.0),
    ],
)
def test_citation_credit(pred: str, gold: str, credit: float) -> None:
    assert citation_credit(_c(pred), _c(gold)) == credit


cits = st.builds(
    Citation,
    kind=st.sampled_from(["para", "art"]),
    number=st.sampled_from(["1", "5a", "622"]),
    absatz=st.sampled_from([None, "1", "2"]),
    law=st.sampled_from(["BGB", "DSGVO"]),
)


@given(cits, cits)
def test_credit_is_one_iff_match(p: Citation, g: Citation) -> None:
    assert (citation_credit(p, g) == 1.0) == citations_match(p, g)
    assert citation_credit(p, g) in (0.0, 0.5, 1.0)


def test_alias_table_v1() -> None:
    table = law_aliases()
    assert table.version == 1
    national = {"BGB", "HGB", "KSchG", "ArbZG", "BDSG", "UrhG", "VVG", "EnWG", "UWG", "GG"}
    assert national <= set(table.national)
    assert {"DSGVO", "KI-VO", "NIS2-RL", "DSA"} <= set(table.eu)
    assert resolve_law("GDPR") == "DSGVO"
    assert resolve_law("german civil code") == "BGB"
    assert resolve_law("Bürgerlichen  Gesetzbuchs") == "BGB"
    assert resolve_law("Nonsense") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("§ 123456 BGB", []),
        ("§§ 622, 1234567 BGB", []),
        ("§ 622 Abs. 2 (3) BGB", []),
        ("§ 622 Abs. 2 Abs. 3 BGB", []),
        ("§ 622 lit. a lit. b BGB", []),
    ],
)
def test_extract_malformed_input(text: str, expected: list[str]) -> None:
    assert [normalise(c) for c in extract_citations(text)] == expected


def test_alias_file_errors_are_config_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda _raw: {"version": 2})
    with pytest.raises(ConfigError, match="invalid"):
        law_aliases.__wrapped__()
    clash = LawAliases(version=1, national={"BGB": ("Gesetz",)}, eu={"DSA": ("gesetz",)})
    with pytest.raises(ConfigError, match="two laws"):
        aliases._lookup_of(clash)
