"""GiiXmlLoader (T2.2): real trimmed GII norms -> Documents; skips, ids, text, counts, errors."""

import unicodedata
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from pathlib import Path

import pytest

from pruefstand.core.enums import Lang
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.corpus import Document
from pruefstand.core.protocols import Loader
from pruefstand.ingest.gii_xml import GiiXmlLoader


RawFactory = Callable[[Mapping[str, Mapping[str, bytes]]], Path]


def load_all(raw: Path) -> tuple[dict[str, Document], GiiXmlLoader]:
    loader = GiiXmlLoader()
    docs = {d.doc_id: d for d in loader.load(raw)}
    return docs, loader


def test_loader_is_a_streaming_loader(raw_dir: Path) -> None:
    loader = GiiXmlLoader()
    assert isinstance(loader, Loader)
    assert isinstance(loader.load(raw_dir), Iterator)


def test_bgb_622_document(raw_dir: Path) -> None:
    docs, _ = load_all(raw_dir)
    doc = docs["gii-bgb-622"]
    assert doc.law_abbrev == "BGB"
    assert "Kündigungsfristen bei Arbeitsverhältnissen" in doc.title
    assert doc.lang is Lang.DE
    assert doc.license == "§5-UrhG"
    assert doc.tenant == "unassigned"
    assert doc.source == "gii:bgb"
    assert doc.url is None
    assert doc.version_date == date(2026, 9, 26)
    assert doc.metadata["citation_key"] == "§ 622 BGB"
    assert doc.metadata["unit"] == "para"
    assert doc.metadata["doknr"] == "BJNR001950896BJNE063807360"
    assert doc.metadata["content_hash"] == stable_hash(doc.text)
    assert doc.metadata["stand"].startswith("zuletzt geändert durch Art. 6 G v. 23.7.2026")


def test_bgb_622_text_keeps_absatz_and_list_structure(raw_dir: Path) -> None:
    text = load_all(raw_dir)[0]["gii-bgb-622"].text
    assert "(2) Für eine Kündigung durch den Arbeitgeber" in text
    assert "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats" in text
    assert "7. 20 Jahre bestanden hat, sieben Monate zum Ende eines Kalendermonats." in text
    lines = text.split("\n")
    assert [ln[:3] for ln in lines if ln.startswith("(")] == [f"({n})" for n in range(1, 7)]
    assert "  " not in text
    assert "Bei der Feststellung der Zahl der beschäftigten Arbeitnehmer" in text


def test_lettered_paragraph_and_skipped_norms(raw_dir: Path) -> None:
    docs, loader = load_all(raw_dir)
    assert docs["gii-bgb-612a"].metadata["citation_key"] == "§ 612a BGB"
    assert {d for d in docs if d.startswith("gii-bgb-")} == {
        "gii-bgb-14", "gii-bgb-612a", "gii-bgb-622",
    }  # fmt: skip
    law = loader.stats.laws["BGB"]
    assert law.norms == 7
    assert law.documents == 3
    assert law.skipped == {"header": 1, "toc": 1, "range": 1, "repealed": 1}
    assert law.errors == 0
    assert law.version_date == date(2026, 9, 26)


def test_footnotes_are_dropped(raw_dir: Path) -> None:
    text = load_all(raw_dir)[0]["gii-bgb-14"].text
    assert text.startswith("(1) Unternehmer ist eine natürliche oder juristische Person")
    assert "Amtlicher Hinweis" not in text
    assert "Diese Vorschrift dient der Umsetzung" not in text


def test_table_rows_become_pipe_rows(raw_dir: Path) -> None:
    text = load_all(raw_dir)[0]["gii-aktg-95"].text
    rows = [ln for ln in text.split("\n") if " | " in ln]
    assert rows
    assert all(not ln.startswith("|") and not ln.endswith("|") for ln in rows)


def test_kschg_and_arbzg_fixtures(raw_dir: Path) -> None:
    docs, _ = load_all(raw_dir)
    kschg = docs["gii-kschg-1"]
    assert kschg.title == "Sozial ungerechtfertigte Kündigungen"
    assert kschg.version_date == date(2026, 5, 6)
    assert "(1) Die Kündigung des Arbeitsverhältnisses gegenüber einem Arbeitnehmer" in kschg.text
    arbzg = docs["gii-arbzg-3"]
    assert arbzg.text.startswith("Die werktägliche Arbeitszeit der Arbeitnehmer darf acht Stunden")
    assert arbzg.version_date == date(2024, 12, 31)


def test_egbgb_article_context(raw_dir: Path) -> None:
    docs, loader = load_all(raw_dir)
    art1 = docs["gii-egbgb-1"]
    assert (art1.law_abbrev, art1.metadata["citation_key"]) == ("EGBGB", "Art. 1 EGBGB")
    assert art1.metadata["unit"] == "art"
    nested = docs["gii-egbgb-246a-1"]
    assert nested.metadata["citation_key"] == "Art. 246a EGBGB"
    assert nested.metadata["section"] == "§ 1"
    assert nested.metadata["article"] == "246a"
    assert "Informationspflichten" in nested.title
    assert loader.stats.laws["EGBGB"].skipped == {"header": 1, "range": 1, "annex": 1}


def test_umlauts_survive_and_text_is_nfc(raw_dir: Path) -> None:
    docs, _ = load_all(raw_dir)
    assert "Kündigung" in docs["gii-kschg-1"].text
    assert "Arbeitsverhältnis" in docs["gii-bgb-622"].text
    for doc in docs.values():
        assert unicodedata.is_normalized("NFC", doc.text)
        assert unicodedata.is_normalized("NFC", doc.title)


def test_nfd_input_is_composed(make_raw: RawFactory, fixture_dir: Path) -> None:
    xml = (fixture_dir / "arbzg_3.xml").read_text(encoding="utf-8")
    decomposed = unicodedata.normalize("NFD", xml.replace("Arbeitszeit der", "Ärbeitszeit der"))
    docs, _ = load_all(make_raw({"arbzg": {"x.xml": decomposed.encode("utf-8")}}))
    doc = docs["gii-arbzg-3"]
    assert "Ärbeitszeit der Arbeitnehmer" in doc.title
    assert unicodedata.is_normalized("NFC", doc.text)


def test_document_order_is_deterministic(raw_dir: Path) -> None:
    first = [d.doc_id for d in GiiXmlLoader().load(raw_dir)]
    assert first == [d.doc_id for d in GiiXmlLoader().load(raw_dir)]
    assert first.index("gii-aktg-95") < first.index("gii-bgb-14") < first.index("gii-kschg-1")


def test_version_date_is_none_without_build_date(make_raw: RawFactory, fixture_dir: Path) -> None:
    xml = (fixture_dir / "arbzg_3.xml").read_text(encoding="utf-8")
    stripped = xml.replace(' builddate="20241231222246"', "")
    docs, loader = load_all(make_raw({"arbzg": {"a.xml": stripped.encode("utf-8")}}))
    assert docs["gii-arbzg-3"].version_date is None
    assert loader.stats.laws["ArbZG"].version_date is None


def test_unknown_law_and_unknown_enbez_are_counted_errors(
    make_raw: RawFactory, fixture_dir: Path
) -> None:
    xml = (fixture_dir / "arbzg_3.xml").read_text(encoding="utf-8")
    unknown_law = xml.replace("<jurabk>ArbZG</jurabk><enbez>§ 3", "<jurabk>NOPE</jurabk><enbez>§ 3")
    odd_enbez = xml.replace("<enbez>§ 3</enbez>", "<enbez>Sonderfall</enbez>")
    for variant, kind in ((unknown_law, "unknown_law"), (odd_enbez, "unknown_enbez")):
        docs, loader = load_all(make_raw({"arbzg": {"a.xml": variant.encode("utf-8")}}))
        assert not [d for d in docs if d.startswith("gii-arbzg-3")]
        assert [p.kind for p in loader.stats.problems] == [kind]


def test_duplicate_document_ids_are_counted_errors(make_raw: RawFactory, fixture_dir: Path) -> None:
    xml = (fixture_dir / "arbzg_3.xml").read_text(encoding="utf-8")
    norm = xml[xml.index('<norm builddate="20241231222246" doknr="BJNR117100994BJNE001100307">'):]
    doubled = xml.replace("</dokumente>", norm.replace("</dokumente>", "") + "</dokumente>")
    docs, loader = load_all(make_raw({"arbzg": {"a.xml": doubled.encode("utf-8")}}))
    assert list(docs) == ["gii-arbzg-3"]
    assert [p.kind for p in loader.stats.problems] == ["duplicate_doc_id"]


def test_bad_archive_is_counted_and_other_laws_still_load(
    make_raw: RawFactory, fixture_dir: Path
) -> None:
    good = (fixture_dir / "kschg_1.xml").read_bytes()
    raw = make_raw({"kschg": {"k.xml": good}, "broken": {"b.xml": b"<dokumente><norm>"}})
    docs, loader = load_all(raw)
    assert "gii-kschg-1" in docs
    assert [p.kind for p in loader.stats.problems] == ["invalid_xml"]
    assert loader.stats.error_count == 1


def test_missing_or_empty_raw_dir_yields_nothing(tmp_path: Path) -> None:
    assert list(GiiXmlLoader().load(tmp_path / "does-not-exist")) == []
    assert list(GiiXmlLoader().load(tmp_path)) == []


def test_non_xml_members_are_ignored(make_raw: RawFactory, fixture_dir: Path) -> None:
    good = (fixture_dir / "kschg_1.xml").read_bytes()
    raw = make_raw({"kschg": {"k.xml": good, "image.jpg": b"\xff\xd8\xff", "dir/": b""}})
    docs, loader = load_all(raw)
    assert list(docs) == ["gii-kschg-1"]
    assert loader.stats.error_count == 0


@pytest.mark.parametrize("name", ["bgb", "egbgb"])
def test_stats_line_counts_are_consistent(raw_dir: Path, name: str) -> None:
    _, loader = load_all(raw_dir)
    law = loader.stats.laws[name.upper() if name != "egbgb" else "EGBGB"]
    assert law.norms == law.documents + sum(law.skipped.values()) + law.errors
