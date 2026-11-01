"""ParagraphChunker (T2.2): one chunk per § / Artikel, long §§ split by Absatz."""

import time
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document
from pruefstand.core.protocols import Chunker
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii_xml import GiiXmlLoader
from pruefstand.ingest.text import count_tokens

WORDS = "Arbeitnehmer Kündigung Frist Betrieb Vertrag Zahlung " * 140  # 840 words


def make_doc(
    text: str, *, metadata: dict[str, str] | None = None, doc_id: str = "gii-bgb-999"
) -> Document:
    return Document(
        doc_id=DocId(doc_id), tenant=TenantId("unassigned"), source="gii:bgb", lang=Lang.DE,
        title="Test", law_abbrev="BGB", version_date=date(2026, 9, 26), text=text,
        license="§5-UrhG", url=None,
        metadata={"citation_key": "§ 999 BGB", **(metadata or {})},
    )  # fmt: skip


def test_protocol_conformance() -> None:
    assert isinstance(ParagraphChunker(), Chunker)


def test_one_paragraph_one_chunk_with_key_and_id(raw_dir: Path) -> None:
    doc = next(d for d in GiiXmlLoader().load(raw_dir) if d.doc_id == "gii-bgb-622")
    (chunk,) = ParagraphChunker().chunk(doc)
    assert chunk.citation_key == "§ 622 BGB"
    assert chunk.chunk_id == "gii-bgb-622#0"
    assert chunk.doc_id == doc.doc_id
    assert chunk.section is None
    assert chunk.text == doc.text
    assert (chunk.tenant, chunk.lang, chunk.source, chunk.license) == (
        "unassigned", Lang.DE, "gii:bgb", "§5-UrhG",
    )  # fmt: skip
    assert chunk.version_date == doc.version_date
    assert chunk.parallel_id is None
    assert chunk.is_attack is False


def test_long_paragraph_splits_by_absatz() -> None:
    text = "\n".join(f"({n}) {WORDS}" for n in (1, 2, 3))
    assert count_tokens(text) > 2000
    chunks = ParagraphChunker().chunk(make_doc(text))
    assert [c.section for c in chunks] == ["Abs. 1", "Abs. 2", "Abs. 3"]
    assert {c.citation_key for c in chunks} == {"§ 999 BGB"}
    assert [c.chunk_id for c in chunks] == [f"gii-bgb-999#{i}" for i in range(3)]
    assert all(c.text.startswith(f"({i + 1}) ") for i, c in enumerate(chunks))


def test_paragraph_at_the_limit_is_not_split() -> None:
    text = "(1) a\n(2) " + "w " * 1990  # 3 + 1 + 3 + 1990 = well below, then pad to exactly 2000
    pad = 2000 - count_tokens(text)
    text += "w " * pad
    assert count_tokens(text) == 2000
    assert len(ParagraphChunker().chunk(make_doc(text))) == 1
    assert len(ParagraphChunker().chunk(make_doc(text + " w"))) == 2


def test_custom_limit_and_validation() -> None:
    text = "(1) eins zwei drei\n(2) vier fünf sechs"
    assert [c.section for c in ParagraphChunker(max_tokens=8).chunk(make_doc(text))] == [
        "Abs. 1", "Abs. 2",
    ]  # fmt: skip
    with pytest.raises(ValueError, match="max_tokens"):
        ParagraphChunker(max_tokens=0)


def test_nested_section_is_kept_and_extended() -> None:
    doc = make_doc("(1) a b c\n(2) d e f", metadata={"section": "§ 1"})
    assert [c.section for c in ParagraphChunker().chunk(doc)] == ["§ 1"]
    assert [c.section for c in ParagraphChunker(max_tokens=5).chunk(doc)] == [
        "§ 1 Abs. 1", "§ 1 Abs. 2",
    ]  # fmt: skip


def test_absatz_numbers_with_letters_and_restarting_lists() -> None:
    text = "(1) a a a\n(1a) b b b\n(2) c c c\n1. Nummer\n(1) nur Liste\n(3) d d d"
    chunks = ParagraphChunker(max_tokens=5).chunk(make_doc(text))
    assert [c.section for c in chunks] == ["Abs. 1", "Abs. 1a", "Abs. 2", "Abs. 3"]
    assert "(1) nur Liste" in chunks[2].text  # a restarted list belongs to its Absatz


def test_text_before_the_first_marker_stays_with_the_first_absatz() -> None:
    text = "Vorbemerkung zum Paragraphen\n(1) eins zwei\n(2) drei vier"
    chunks = ParagraphChunker(max_tokens=4).chunk(make_doc(text))
    assert [c.section for c in chunks] == ["Abs. 1", "Abs. 2"]
    assert chunks[0].text.startswith("Vorbemerkung")


def test_oversize_text_without_markers_or_single_absatz_stays_whole() -> None:
    chunks = ParagraphChunker(max_tokens=5).chunk(make_doc("eins zwei drei vier fünf sechs sieben"))
    assert [(c.section, c.chunk_id) for c in chunks] == [(None, "gii-bgb-999#0")]
    only_one = ParagraphChunker(max_tokens=5).chunk(make_doc("(1) eins zwei drei vier fünf sechs"))
    assert len(only_one) == 1


def test_blank_document_yields_no_chunks() -> None:
    assert ParagraphChunker().chunk(make_doc("  \n ")) == []


def test_document_without_citation_key_gets_none() -> None:
    doc = make_doc("(1) x")
    bare = doc.model_copy(update={"metadata": {}})
    assert ParagraphChunker().chunk(bare)[0].citation_key is None


def squeeze(text: str) -> str:
    return "".join(text.split())


@given(
    st.lists(st.text(alphabet=st.sampled_from(list("ab (1)2.\n\t-äß§")), max_size=40), max_size=12),
    st.integers(min_value=1, max_value=12),
)
def test_chunk_texts_concatenate_to_the_document_text(parts: list[str], limit: int) -> None:
    text = "\n".join(parts)
    chunks = ParagraphChunker(max_tokens=limit).chunk(make_doc(text))
    assert squeeze("".join(c.text for c in chunks)) == squeeze(text)
    assert [c.chunk_id for c in chunks] == [f"gii-bgb-999#{i}" for i in range(len(chunks))]


@pytest.mark.parametrize(
    "unit", ["(1) ", "(", "\n(1)", "a ", "(1)\n(2)\n", "((((((((", "ä" * 50 + "\n"]
)
def test_chunker_is_linear_on_pathological_text(unit: str) -> None:
    chunker = ParagraphChunker(max_tokens=50)

    def run(n: int) -> float:
        doc = make_doc(unit * n)
        start = time.perf_counter()
        chunker.chunk(doc)
        return time.perf_counter() - start

    small = min(run(5_000) for _ in range(3))
    large = min(run(40_000) for _ in range(3))
    assert large < 3.0
    assert large < 8 * 6 * max(small, 0.002)
