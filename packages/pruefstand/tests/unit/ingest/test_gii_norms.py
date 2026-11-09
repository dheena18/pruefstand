"""Classification of GII norms and builddate parsing (T2.2), driven by real `<norm>` metadata."""

from datetime import date

import pytest
from lxml import etree
from testsupport.timing import cpu_budget

from pruefstand.ingest.gii.norms import (
    NormMeta,
    Reject,
    Skip,
    Unit,
    classify,
    parse_builddate,
    read_meta,
    read_stand,
)

NORM = (
    '<norm builddate="20260926215508" doknr="X"><metadaten><jurabk>BGB</jurabk>{enbez}{gl}'
    "<titel>T</titel></metadaten><textdaten/></norm>"
)
GLIEDERUNG = (
    "<gliederungseinheit><gliederungskennzahl>1</gliederungskennzahl>"
    "<gliederungsbez>{bez}</gliederungsbez><gliederungstitel/></gliederungseinheit>"
)


def meta_of(enbez: str | None = None, gliederung: str | None = None) -> NormMeta:
    en = "" if enbez is None else f"<enbez>{enbez}</enbez>"
    gl = "" if gliederung is None else GLIEDERUNG.format(bez=gliederung)
    return read_meta(etree.fromstring(NORM.format(enbez=en, gl=gl)))


@pytest.mark.parametrize(
    ("enbez", "gliederung", "expected"),
    [
        ("§ 622", None, Unit("para", "622")),
        ("§ 626a", None, Unit("para", "626a")),
        ("§ 612a", None, Unit("para", "612a")),
        ("Art 5", None, Unit("art", "5")),
        ("Art. 12", None, Unit("art", "12")),
        ("Artikel 3", None, Unit("art", "3")),
        ("§ 1", "Art 246a", Unit("art", "246a", "1")),
        ("§ 1", "Erster Teil", Unit("para", "1")),
        ("Inhaltsübersicht", None, Skip("toc")),
        ("Eingangsformel", None, Skip("preamble")),
        ("Anlage 1", None, Skip("annex")),
        ("Anhang EV", None, Skip("annex")),
        ("(XXXX) §§ 3 bis 6", None, Skip("range")),
        ("(XXXX)§§ 2354 bis 2359", None, Skip("range")),
        ("(XXXX) §§ 13b u. 13c", None, Skip("range")),
        (None, None, Skip("header")),
        (None, "Erster Abschnitt", Skip("structure")),
        (None, "Art 27 bis 37", Skip("range")),
        (None, "Art 57 und 58", Skip("range")),
        (None, "Art 1", Unit("art", "1", from_gliederung=True)),
        ("Sonderfall", None, Reject("unknown_enbez", "Sonderfall")),
        ("§ 12345678", None, Reject("unknown_enbez", "§ 12345678")),
    ],
)
def test_classify(
    enbez: str | None, gliederung: str | None, expected: Unit | Skip | Reject
) -> None:
    assert classify(meta_of(enbez, gliederung)) == expected


def test_unit_suffix_and_section() -> None:
    assert (Unit("para", "622").suffix, Unit("para", "622").section) == ("622", None)
    nested = Unit("art", "246a", "1")
    assert (nested.suffix, nested.section) == ("246a-1", "§ 1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20260926215508", date(2026, 9, 26)),
        ("20241231", date(2024, 12, 31)),
        ("20261301000000", None),
        ("2026", None),
        ("", None),
        (None, None),
        ("abcdefgh", None),
    ],
)
def test_parse_builddate(value: str | None, expected: date | None) -> None:
    assert parse_builddate(value) == expected


def test_read_stand_takes_the_stand_remark_only() -> None:
    xml = (
        "<norm><metadaten><standangabe><standtyp>Neuf</standtyp>"
        "<standkommentar>Neugefasst durch Bek.</standkommentar></standangabe>"
        "<standangabe><standtyp>Stand</standtyp><standkommentar>Zuletzt  geändert durch\nArt. 2"
        "</standkommentar></standangabe></metadaten></norm>"
    )
    assert read_stand(etree.fromstring(xml)) == "Zuletzt geändert durch Art. 2"
    assert read_stand(etree.fromstring("<norm><metadaten/></norm>")) is None


def test_pathological_labels_are_cut_and_fast() -> None:
    evil = "Art§§" * 200_000
    with cpu_budget(1.0):
        meta = meta_of(evil, evil)
        verdict = classify(meta)
    assert len(meta.enbez) == len(meta.gliederung_bez) == 200
    assert isinstance(verdict, Reject | Skip)
