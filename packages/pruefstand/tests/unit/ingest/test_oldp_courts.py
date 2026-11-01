"""Court classification for T2.5 tenant planning (T2.3 S5): jurisdiction, level, domain."""

import pytest

from pruefstand.ingest.oldp_courts import classify_court, tenant_domain


@pytest.mark.parametrize(
    ("name", "field", "expected"),
    [
        ("Arbeitsgericht Frankfurt am Main", None, "Arbeitsgericht"),
        ("Hessisches Landesarbeitsgericht", "Arbeitsgerichtsbarkeit", "Arbeitsgericht"),
        ("Bundesarbeitsgericht", None, "Arbeitsgericht"),
        ("Sozialgericht Darmstadt", None, "Sozialgericht"),
        ("Landessozialgericht Baden-Württemberg", None, "Sozialgericht"),
        ("Bundessozialgericht", None, "Sozialgericht"),
        ("Amtsgericht Düsseldorf", None, "Zivilgericht"),
        ("Landgericht Hagen", None, "Zivilgericht"),
        ("Oberlandesgericht Hamm", None, "Zivilgericht"),
        ("Hanseatisches Oberlandesgericht", None, "Zivilgericht"),
        ("Kammergericht", None, "Zivilgericht"),
        ("Bundesgerichtshof", None, "Zivilgericht"),
        ("Verwaltungsgericht Köln", None, "Verwaltungsgericht"),
        ("Sächsisches Oberverwaltungsgericht", None, "Verwaltungsgericht"),
        ("Verwaltungsgerichtshof Baden-Württemberg", None, "Verwaltungsgericht"),
        ("Bundesverwaltungsgericht", None, "Verwaltungsgericht"),
        ("Finanzgericht Rheinland-Pfalz", None, "Finanzgericht"),
        ("Bundesfinanzhof", None, "Finanzgericht"),
        ("Bundesverfassungsgericht", None, "Verfassungsgericht"),
        ("Verfassungsgerichtshof des Freistaates Sachsen", None, "Verfassungsgericht"),
        ("Unknown court", "Arbeitsgerichtsbarkeit", "Arbeitsgericht"),
        ("Unknown court", "Ordentliche Gerichtsbarkeit", "Zivilgericht"),
        ("Unknown court", None, "Sonstige"),
        ("Bundespatentgericht", None, "Sonstige"),
        ("", None, "Sonstige"),
    ],
)
def test_jurisdiction_comes_from_the_court_name_first(
    name: str, field: str | None, expected: str
) -> None:
    assert classify_court(name, field, None).jurisdiction == expected


@pytest.mark.parametrize(
    ("name", "given", "expected"),
    [
        ("Amtsgericht Köln", None, "Amtsgericht"),
        ("Landgericht Bonn", "Landgericht", "Landgericht"),
        ("Oberlandesgericht Hamm", None, "Oberlandesgericht"),
        ("Kammergericht", None, "Oberlandesgericht"),
        ("Bundesarbeitsgericht", None, "Bundesgericht"),
        ("Bundesgerichtshof", "Bundesgericht", "Bundesgericht"),
        ("Verwaltungsgericht Köln", None, ""),
        ("Verwaltungsgericht Köln", "Amtsgericht", "Amtsgericht"),
    ],
)
def test_court_level(name: str, given: str | None, expected: str) -> None:
    assert classify_court(name, None, given).level == expected


def test_labour_courts_are_labour_whatever_the_text_says() -> None:
    assert tenant_domain("Arbeitsgericht", "Versicherung Versicherung") == "labour"


@pytest.mark.parametrize(
    "jurisdiction", ["Zivilgericht", "Sozialgericht", "Verwaltungsgericht", "Sonstige"]
)
def test_insurance_needs_the_word_in_the_head_of_the_text(jurisdiction: str) -> None:
    assert (
        tenant_domain(jurisdiction, "Streit um die Hausratsversicherungsbedingungen") == "insurance"
    )
    assert tenant_domain(jurisdiction, "Streit um die Krankenversicherung") == "insurance"
    assert tenant_domain(jurisdiction, "Streit um die Miete") == "other"


def test_only_the_first_4000_characters_count() -> None:
    assert tenant_domain("Zivilgericht", "x" * 4000 + "Versicherung") == "other"
    assert tenant_domain("Zivilgericht", "x" * 3980 + "Versicherung") == "insurance"
