"""ArticleChunker and aligned chunking on the trimmed GDPR fixtures (T2.4)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pruefstand.core.citations import extract_citations, normalise
from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.align import chunk_aligned
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.eurlex_blocks import parse_blocks
from pruefstand.ingest.text import count_tokens

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eurlex"
CELEX = "32016R0679"


@pytest.fixture(scope="module")
def docs(tmp_path_factory: pytest.TempPathFactory) -> dict[Lang, Document]:
    target = tmp_path_factory.mktemp("raw") / CELEX
    target.mkdir()
    for lang in ("de", "en"):
        (target / f"{lang}.html").write_bytes((FIXTURES / f"gdpr_{lang}.html").read_bytes())
    return {d.lang: d for d in EurLexLoader().load(target.parent)}


def by_pid(chunks: list[Chunk]) -> dict[str, Chunk]:
    return {c.parallel_id: c for c in chunks if c.parallel_id is not None}


def test_german_article_6(docs: dict[Lang, Document]) -> None:
    chunk = by_pid(ArticleChunker().chunk(docs[Lang.DE]))[f"{CELEX}:art-6"]
    assert chunk.citation_key == "Art. 6 DSGVO"
    assert "Rechtmäßigkeit der Verarbeitung" in chunk.text
    assert chunk.text.startswith("Artikel 6")
    assert chunk.lang == Lang.DE
    assert chunk.section is None


def test_english_article_6_carries_the_german_key(docs: dict[Lang, Document]) -> None:
    assert docs[Lang.EN].metadata["citation_en"] == "GDPR"
    chunk = by_pid(ArticleChunker().chunk(docs[Lang.EN]))[f"{CELEX}:art-6"]
    assert chunk.citation_key == "Art. 6 DSGVO"
    assert "Lawfulness of processing" in chunk.text
    assert chunk.text.startswith("Article 6")
    assert chunk.lang == Lang.EN


def test_chunk_has_no_metadata_field() -> None:
    with pytest.raises(ValidationError):
        Chunk.model_validate(
            {
                "chunk_id": "c", "doc_id": "d", "tenant": "t", "lang": "en", "text": "x",
                "citation_key": None, "section": None, "parallel_id": None, "version_date": None,
                "license": "EU-2011/833", "source": "s", "metadata": {"citation_en": "GDPR"},
            }
        )  # fmt: skip


def test_parallel_ids_are_shared_between_languages(docs: dict[Lang, Document]) -> None:
    de, en = (by_pid(ArticleChunker().chunk(docs[lang])) for lang in (Lang.DE, Lang.EN))
    assert set(de) == set(en)
    assert f"{CELEX}:art-6" in de
    assert f"{CELEX}:art-5" in de


def test_recitals_one_to_ten_are_two_aligned_chunks_per_language(
    docs: dict[Lang, Document],
) -> None:
    for lang, label in ((Lang.DE, "Erwägungsgründe"), (Lang.EN, "Recitals")):
        recitals = [c for c in ArticleChunker().chunk(docs[lang]) if c.citation_key is None]
        assert [c.section for c in recitals] == [f"{label} 1–5", f"{label} 6–10"]
        assert [c.parallel_id for c in recitals] == [f"{CELEX}:rec-1-5", f"{CELEX}:rec-6-10"]
        assert recitals[0].text.startswith(f"{label} 1–5")
        assert "(5)" in recitals[0].text
        assert "(6)" not in recitals[0].text


def test_last_recital_block_may_be_shorter(docs: dict[Lang, Document]) -> None:
    chunks = ArticleChunker(recital_group=4).chunk(docs[Lang.EN])
    recitals = [c for c in chunks if c.citation_key is None]
    assert [c.section for c in recitals] == ["Recitals 1–4", "Recitals 5–8", "Recitals 9–10"]


def test_single_recital_block_label(docs: dict[Lang, Document]) -> None:
    chunks = ArticleChunker(recital_group=3).chunk(docs[Lang.DE])
    recitals = [c for c in chunks if c.citation_key is None]
    assert recitals[-1].section == "Erwägungsgrund 10"
    assert recitals[-1].parallel_id == f"{CELEX}:rec-10"


def test_chunk_ids_are_unique_and_prefixed_with_the_doc_id(docs: dict[Lang, Document]) -> None:
    chunks = ArticleChunker().chunk(docs[Lang.DE])
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert all(c.chunk_id.startswith("eurlex-32016R0679-de#") for c in chunks)
    assert all(c.license == "EU-2011/833" and c.source == "eurlex:32016R0679" for c in chunks)
    assert all(c.version_date == docs[Lang.DE].version_date for c in chunks)


def test_long_article_splits_by_paragraph_and_stays_aligned(docs: dict[Lang, Document]) -> None:
    chunker = ArticleChunker(max_tokens=200)
    de, en = chunk_aligned(chunker, docs[Lang.DE], docs[Lang.EN])
    for chunks in (de, en):
        art6 = [c for c in chunks if c.citation_key == "Art. 6 DSGVO"]
        assert [c.section for c in art6] == [f"Art. 6 Abs. {n}" for n in (1, 2, 3, 4)]
        assert [c.parallel_id for c in art6] == [f"{CELEX}:art-6:abs-{n}" for n in (1, 2, 3, 4)]
    assert [c.parallel_id for c in de] == [c.parallel_id for c in en]


def test_split_chunks_keep_the_article_heading(docs: dict[Lang, Document]) -> None:
    chunks = ArticleChunker(max_tokens=200).chunk(docs[Lang.EN])
    art6 = [c for c in chunks if c.citation_key == "Art. 6 DSGVO"]
    assert all(c.text.startswith("Article 6") for c in art6)
    assert all("Lawfulness of processing" in c.text.splitlines()[0] for c in art6)


def test_split_is_decided_for_both_languages_together(docs: dict[Lang, Document]) -> None:
    art6 = {
        lang: next(b for b in parse_blocks(docs[lang].text) if b.block_id == "art-6")
        for lang in (Lang.DE, Lang.EN)
    }
    tokens = {lang: count_tokens(block.body) for lang, block in art6.items()}
    low, high = sorted(tokens.values())
    assert low < high
    chunker = ArticleChunker(max_tokens=low)
    alone = {lang: by_pid(chunker.chunk(docs[lang])) for lang in tokens}
    assert alone[Lang.DE].keys() != alone[Lang.EN].keys()  # one language splits, the other not
    de, en = chunk_aligned(chunker, docs[Lang.DE], docs[Lang.EN])
    assert [c.parallel_id for c in de] == [c.parallel_id for c in en]
    assert f"{CELEX}:art-6:abs-1" in {c.parallel_id for c in en}


def test_article_without_numbered_paragraphs_is_never_cut() -> None:
    doc = Document(
        doc_id=DocId("eurlex-1-en"), tenant=TenantId("unassigned"), source="eurlex:1", lang=Lang.EN,
        title="t", law_abbrev="DSGVO", version_date=None,
        text="\x1eART 1\tScope\nOne long sentence " + "word " * 50, license="EU-2011/833",
        url=None, metadata={"celex": "1"},
    )  # fmt: skip
    (chunk,) = ArticleChunker(max_tokens=5).chunk(doc)
    assert chunk.section is None
    assert chunk.parallel_id == "1:art-1"


def test_paragraph_numbers_must_run_one_two_three(docs: dict[Lang, Document]) -> None:
    doc = docs[Lang.EN].model_copy(
        update={"text": "\x1eART 7\tT\n1. first\n3. skip\n2. second\n2. restarted list"}
    )
    chunks = ArticleChunker(max_tokens=2).chunk(doc)
    assert [c.section for c in chunks] == ["Art. 7 Abs. 1", "Art. 7 Abs. 2"]
    assert "3. skip" in chunks[0].text


def test_article_with_an_intro_sentence_is_a_list_and_never_split(
    docs: dict[Lang, Document],
) -> None:
    text = (
        "\x1eART 4\tBegriffsbestimmungen\nIm Sinne dieser Verordnung:\n(1) erstens;\n(2) zweitens."
    )
    doc = docs[Lang.DE].model_copy(update={"text": text})
    (chunk,) = ArticleChunker(max_tokens=2).chunk(doc)
    assert chunk.section is None
    assert chunk.parallel_id == "32016R0679:art-4"


def test_empty_document_has_no_chunks(docs: dict[Lang, Document]) -> None:
    assert ArticleChunker().chunk(docs[Lang.EN].model_copy(update={"text": " \n"})) == []


def test_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        ArticleChunker(max_tokens=0)
    with pytest.raises(ValueError, match="recital_group"):
        ArticleChunker(recital_group=0)


def test_chunk_aligned_names_the_missing_parallel_id(docs: dict[Lang, Document]) -> None:
    short = docs[Lang.EN].model_copy(update={"text": docs[Lang.EN].text.split("\x1eART 6")[0]})
    with pytest.raises(DatasetError, match=r"32016R0679.*art-6"):
        chunk_aligned(ArticleChunker(), docs[Lang.DE], short)


def test_article_keys_round_trip_through_the_citation_parser(docs: dict[Lang, Document]) -> None:
    for chunk in ArticleChunker().chunk(docs[Lang.EN]):
        if chunk.citation_key is not None:
            assert normalise(extract_citations(chunk.citation_key)[0]) == chunk.citation_key
