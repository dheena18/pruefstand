"""EurLexLoader and the alignment validator on real, trimmed EUR-Lex fixtures (T2.4)."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from lxml import html
from pruefstand.ingest.align import check_aligned
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.eurlex_blocks import Block, parse_blocks

from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Document

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eurlex"
CELEX = "32016R0679"


def build_raw(tmp_path: Path, de: bytes, en: bytes, celex: str = CELEX) -> Path:
    target = tmp_path / "raw" / celex
    target.mkdir(parents=True)
    (target / "de.html").write_bytes(de)
    (target / "en.html").write_bytes(en)
    return tmp_path / "raw"


def gdpr(lang: str) -> bytes:
    return (FIXTURES / f"gdpr_{lang}.html").read_bytes()


def drop_div(data: bytes, div_id: str) -> bytes:
    doc = html.document_fromstring(data, parser=html.HTMLParser(encoding="utf-8"))
    for div in doc.xpath(f'//div[@id="{div_id}"]'):
        div.getparent().remove(div)
    return html.tostring(doc, encoding="utf-8")


def flatten(data: bytes) -> bytes:
    """Remove the ELI wrapper divs of articles and recitals: the older flat OJ layout."""
    doc = html.document_fromstring(data, parser=html.HTMLParser(encoding="utf-8"))
    for div in doc.xpath('//div[starts-with(@id,"art_") or starts-with(@id,"rct_")]'):
        if "." not in div.get("id", ""):
            div.drop_tag()
    for div in doc.xpath('//div[contains(@class,"eli-title")]'):
        div.drop_tag()
    return html.tostring(doc, encoding="utf-8")


@pytest.fixture
def docs(tmp_path: Path) -> dict[Lang, Document]:
    loader = EurLexLoader()
    loaded = list(loader.load(build_raw(tmp_path, gdpr("de"), gdpr("en"))))
    return {d.lang: d for d in loaded}


def blocks_of(doc: Document) -> list[Block]:
    return parse_blocks(doc.text)


def test_german_document(docs: dict[Lang, Document]) -> None:
    doc = docs[Lang.DE]
    assert doc.lang == Lang.DE
    assert doc.metadata["celex"] == CELEX
    assert doc.law_abbrev == "DSGVO"
    assert doc.doc_id == "eurlex-32016R0679-de"
    assert doc.source == "eurlex:32016R0679"
    assert doc.license == "EU-2011/833"
    assert doc.metadata["attribution"] == "© European Union, https://eur-lex.europa.eu"
    assert doc.version_date == date(2016, 5, 4)
    assert "VERORDNUNG (EU) 2016/679" in doc.title
    assert doc.url is not None
    assert doc.url.endswith("CELEX:32016R0679")


def test_english_document(docs: dict[Lang, Document]) -> None:
    doc = docs[Lang.EN]
    assert doc.lang == Lang.EN
    assert doc.metadata["celex"] == CELEX
    assert doc.metadata["citation_en"] == "GDPR"
    assert doc.law_abbrev == "DSGVO"
    assert doc.doc_id == "eurlex-32016R0679-en"
    assert "REGULATION (EU) 2016/679" in doc.title


def test_blocks_are_ten_recitals_and_two_articles(docs: dict[Lang, Document]) -> None:
    for doc in docs.values():
        blocks = blocks_of(doc)
        assert [(b.kind, b.number) for b in blocks if b.kind == "art"] == [
            ("art", "5"),
            ("art", "6"),
        ]
        assert [b.number for b in blocks if b.kind == "rec"] == [str(i) for i in range(1, 11)]


def test_article_titles_and_text(docs: dict[Lang, Document]) -> None:
    de = {b.number: b for b in blocks_of(docs[Lang.DE]) if b.kind == "art"}
    en = {b.number: b for b in blocks_of(docs[Lang.EN]) if b.kind == "art"}
    assert de["6"].title == "Rechtmäßigkeit der Verarbeitung"
    assert en["6"].title == "Lawfulness of processing"
    assert "1. Die Verarbeitung ist nur rechtmäßig" in de["6"].body
    assert "(a) the data subject has given consent" in en["6"].body


def test_footnote_markers_are_dropped(docs: dict[Lang, Document]) -> None:
    recital3 = next(b for b in blocks_of(docs[Lang.EN]) if b.kind == "rec" and b.number == "3")
    assert "Directive 95/46/EC of the European Parliament and of the Council seeks" in " ".join(
        recital3.body.split()
    )


def test_unprefixed_ti_art_class_gives_the_same_blocks(
    tmp_path: Path, docs: dict[Lang, Document]
) -> None:
    de, en = (gdpr(x).replace(b"oj-ti-art", b"ti-art").replace(b"oj-sti-art", b"sti-art")
              for x in ("de", "en"))  # fmt: skip
    loaded = {d.lang: d for d in EurLexLoader().load(build_raw(tmp_path, de, en))}
    assert loaded[Lang.EN].text == docs[Lang.EN].text
    assert loaded[Lang.DE].text == docs[Lang.DE].text


@pytest.mark.parametrize("prefix", [b"oj-", b""])
def test_flat_layout_gives_the_same_blocks(
    tmp_path: Path, docs: dict[Lang, Document], prefix: bytes
) -> None:
    de, en = (flatten(gdpr(x)).replace(b"oj-ti-art", prefix + b"ti-art") for x in ("de", "en"))
    loaded = {d.lang: d for d in EurLexLoader().load(build_raw(tmp_path, de, en))}
    assert loaded[Lang.EN].text == docs[Lang.EN].text
    assert loaded[Lang.DE].text == docs[Lang.DE].text


def test_quoted_article_heading_is_not_an_article(tmp_path: Path) -> None:
    quote = b'<p class="oj-ti-art">\xe2\x80\x98Article 8a</p>'
    de, en = (gdpr(x).replace(b'<div id="006.001">', b'<div id="006.001">' + quote, 1)
              for x in ("de", "en"))  # fmt: skip
    loaded = list(EurLexLoader().load(build_raw(tmp_path, flatten(de), flatten(en))))
    numbers = [b.number for b in blocks_of(loaded[1]) if b.kind == "art"]
    assert numbers == ["5", "6"]


# --- legacy plain layout (Directive 2003/88/EC, 2002/58/EC) -------------------------------------


@pytest.fixture
def legacy(tmp_path: Path) -> dict[Lang, Document]:
    de, en = ((FIXTURES / f"workingtime_{x}.html").read_bytes() for x in ("de", "en"))
    raw = build_raw(tmp_path, de, en, celex="32003L0088")
    return {d.lang: d for d in EurLexLoader().load(raw)}


def test_legacy_layout_articles_and_recitals(legacy: dict[Lang, Document]) -> None:
    for doc in legacy.values():
        blocks = blocks_of(doc)
        assert [b.number for b in blocks if b.kind == "rec"] == ["1", "2", "3", "4", "5"]
        assert [b.number for b in blocks if b.kind == "art"] == ["1", "2", "3"]
    de = {b.number: b for b in blocks_of(legacy[Lang.DE]) if b.kind == "art"}
    en = {b.number: b for b in blocks_of(legacy[Lang.EN]) if b.kind == "art"}
    assert (de["1"].title, en["1"].title) == (
        "Gegenstand und Anwendungsbereich",
        "Purpose and scope",
    )
    assert legacy[Lang.EN].law_abbrev == "Arbeitszeit-RL"
    assert legacy[Lang.EN].version_date == date(2003, 11, 18)


def test_legacy_layout_stops_at_the_signature_and_annexes(legacy: dict[Lang, Document]) -> None:
    art3 = next(b for b in blocks_of(legacy[Lang.EN]) if b.number == "3")
    assert art3.body == (
        "Member States shall take the measures necessary to ensure that every worker is "
        "entitled to a minimum daily rest period of 11 consecutive hours per 24-hour period."
    )
    assert "Done at Brussels" not in legacy[Lang.EN].text
    assert "CHAPTER" not in legacy[Lang.EN].text


# --- loader behaviour ---------------------------------------------------------------------------


def test_documents_are_deterministic_and_sorted(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, gdpr("de"), gdpr("en"))
    first = list(EurLexLoader().load(raw))
    assert first == list(EurLexLoader().load(raw))
    assert [d.lang for d in first] == [Lang.DE, Lang.EN]


def test_missing_language_file_skips_the_act_and_counts(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, gdpr("de"), gdpr("en"))
    (raw / CELEX / "en.html").unlink()
    loader = EurLexLoader()
    assert list(loader.load(raw)) == []
    assert [(p.celex, p.kind) for p in loader.stats.problems] == [(CELEX, "missing_file")]


def test_unknown_celex_is_a_counted_problem(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, gdpr("de"), gdpr("en"), celex="31999L9999")
    loader = EurLexLoader()
    assert list(loader.load(raw)) == []
    assert [p.kind for p in loader.stats.problems] == ["unknown_act"]


def test_expected_acts_without_directory_are_reported(tmp_path: Path) -> None:
    loader = EurLexLoader(expected=[CELEX, "32024R1689"])
    list(loader.load(build_raw(tmp_path, gdpr("de"), gdpr("en"))))
    assert [(p.celex, p.kind) for p in loader.stats.problems] == [("32024R1689", "missing_act")]


def test_missing_directory_yields_nothing(tmp_path: Path) -> None:
    assert list(EurLexLoader().load(tmp_path / "nope")) == []


def test_html_without_articles_is_a_counted_problem(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, b"<html><body><p>nothing</p></body></html>", gdpr("en"))
    loader = EurLexLoader()
    assert list(loader.load(raw)) == []
    assert [p.kind for p in loader.stats.problems] == ["no_articles"]


# --- alignment ----------------------------------------------------------------------------------


def test_missing_english_article_raises_naming_act_and_article(docs: dict[Lang, Document]) -> None:
    en = [b for b in blocks_of(docs[Lang.EN]) if b.number != "6" or b.kind == "rec"]
    with pytest.raises(DatasetError) as err:
        check_aligned(CELEX, blocks_of(docs[Lang.DE]), en)
    assert CELEX in str(err.value)
    assert "art-6" in str(err.value)


def test_misaligned_act_is_skipped_and_counted(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, gdpr("de"), drop_div(gdpr("en"), "art_6"))
    loader = EurLexLoader()
    assert list(loader.load(raw)) == []
    assert loader.stats.misaligned_acts == 1
    (problem,) = loader.stats.problems
    assert problem.kind == "misaligned"
    assert CELEX in problem.detail
    assert "art-6" in problem.detail


def test_missing_recital_is_a_misalignment_too(tmp_path: Path) -> None:
    raw = build_raw(tmp_path, gdpr("de"), drop_div(gdpr("en"), "rct_10"))
    loader = EurLexLoader()
    assert list(loader.load(raw)) == []
    assert "rec-10" in loader.stats.problems[0].detail


def test_aligned_act_passes_the_validator(docs: dict[Lang, Document]) -> None:
    check_aligned(CELEX, blocks_of(docs[Lang.DE]), blocks_of(docs[Lang.EN]))


def test_copying_the_fixture_dir_layout_matches_make_data(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw" / "eurlex" / CELEX
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gdpr_de.html", raw / "de.html")
    shutil.copy(FIXTURES / "gdpr_en.html", raw / "en.html")
    assert len(list(EurLexLoader().load(raw.parent))) == 2
