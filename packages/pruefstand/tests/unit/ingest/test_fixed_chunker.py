"""FixedTokenChunker (T2.3): token windows with overlap, word-safe, stable ids, linear time."""

import math
import time
import unicodedata
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pruefstand.ingest.chunkers.fixed import FixedTokenChunker, token_windows

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document
from pruefstand.core.protocols import Chunker
from pruefstand.ingest.text import count_tokens


def make_doc(text: str, doc_id: str = "oldp-123") -> Document:
    return Document(
        doc_id=DocId(doc_id), tenant=TenantId("unassigned"), source="oldp:decisions", lang=Lang.DE,
        title="Test", law_abbrev=None, version_date=date(2024, 1, 25), text=text,
        license="ODbL-1.0", url=None,
    )  # fmt: skip


def words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def test_protocol_conformance() -> None:
    assert isinstance(FixedTokenChunker(), Chunker)


def test_defaults_are_512_and_64() -> None:
    chunker = FixedTokenChunker()
    assert (chunker.max_tokens, chunker.overlap) == (512, 64)


def test_25_tokens_make_four_windows_at_0_7_14_21() -> None:
    chunks = FixedTokenChunker(max_tokens=10, overlap=3).chunk(make_doc(words(25)))
    starts = [int(c.text.split()[0][1:]) for c in chunks]
    assert starts == [0, 7, 14, 21]
    assert [len(c.text.split()) for c in chunks] == [10, 10, 10, 4]  # the last one is shorter
    for first, second in zip(chunks, chunks[1:], strict=False):
        assert first.text.split()[-3:] == second.text.split()[:3]
    assert {w for c in chunks for w in c.text.split()} == {f"w{i}" for i in range(25)}


def test_empty_and_blank_documents_have_no_chunks() -> None:
    chunker = FixedTokenChunker(max_tokens=10, overlap=3)
    assert chunker.chunk(make_doc("")) == []
    assert chunker.chunk(make_doc(" \n\t ")) == []


def test_ten_token_document_is_one_chunk() -> None:
    (chunk,) = FixedTokenChunker(max_tokens=10, overlap=3).chunk(make_doc(words(10)))
    assert chunk.text == words(10)


def test_window_ending_exactly_at_the_end_adds_no_tail_chunk() -> None:
    chunks = FixedTokenChunker(max_tokens=10, overlap=3).chunk(make_doc(words(17)))
    assert [int(c.text.split()[0][1:]) for c in chunks] == [0, 7]


def test_chunk_fields_follow_the_document() -> None:
    doc = make_doc(words(25))
    chunks = FixedTokenChunker(max_tokens=10, overlap=3).chunk(doc)
    assert [c.chunk_id for c in chunks] == [f"oldp-123#{i}" for i in range(4)]
    for chunk in chunks:
        assert (chunk.doc_id, chunk.tenant, chunk.lang) == (doc.doc_id, doc.tenant, Lang.DE)
        assert (chunk.license, chunk.source, chunk.version_date) == (
            "ODbL-1.0",
            doc.source,
            doc.version_date,
        )
        assert chunk.section is None
        assert chunk.citation_key is None
        assert chunk.is_attack is False


def test_ids_and_texts_are_stable_across_runs() -> None:
    doc = make_doc(words(300))
    first = FixedTokenChunker(max_tokens=50, overlap=5).chunk(doc)
    second = FixedTokenChunker(max_tokens=50, overlap=5).chunk(doc)
    assert first == second


def test_boundaries_never_split_words_or_combining_characters() -> None:
    nfc_text = "Die Kündigungsschutzgesetz Straße Änderungskündigung gilt in der Straße " * 4
    for text in (nfc_text, unicodedata.normalize("NFD", nfc_text)):
        for chunk in FixedTokenChunker(max_tokens=3, overlap=1).chunk(make_doc(text)):
            assert not unicodedata.combining(chunk.text[0])
            assert chunk.text == chunk.text.strip()
            for word in chunk.text.split():
                assert word in text.split()  # an intact word of the source
    for chunk in FixedTokenChunker(max_tokens=3, overlap=1).chunk(make_doc(nfc_text)):
        assert unicodedata.is_normalized("NFC", chunk.text)


def test_chunk_text_keeps_the_source_line_breaks() -> None:
    (chunk,) = FixedTokenChunker(max_tokens=10, overlap=3).chunk(make_doc("Tenor\n1\nDie Klage."))
    assert chunk.text == "Tenor\n1\nDie Klage."


@pytest.mark.parametrize(("max_tokens", "overlap"), [(0, 0), (-1, 0), (10, 10), (10, 11), (10, -1)])
def test_invalid_parameters_raise(max_tokens: int, overlap: int) -> None:
    with pytest.raises(ValueError, match=r"max_tokens|overlap"):
        FixedTokenChunker(max_tokens=max_tokens, overlap=overlap)


@settings(max_examples=150, deadline=None)
@given(
    n=st.integers(0, 300),
    max_tokens=st.integers(1, 40),
    data=st.data(),
)
def test_windows_cover_every_token_with_exact_overlap(
    n: int, max_tokens: int, data: st.DataObject
) -> None:
    overlap = data.draw(st.integers(0, max_tokens - 1))
    windows = token_windows(words(n), max_tokens, overlap)
    if n == 0:
        assert windows == []
        return
    step = max_tokens - overlap
    expected = 1 if n <= max_tokens else 1 + math.ceil((n - max_tokens) / step)
    assert len(windows) == expected
    assert {t for w in windows for t in w.split()} == {f"w{i}" for i in range(n)}
    for first, second in zip(windows, windows[1:], strict=False):
        assert len(first.split()) == max_tokens
        if overlap:
            assert first.split()[-overlap:] == second.split()[:overlap]
    assert all(count_tokens(w) <= max_tokens for w in windows)


def best_of(runs: int, text: str, chunker: FixedTokenChunker) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        chunker.chunk(make_doc(text))
        best = min(best, time.perf_counter() - start)
    return best


def test_time_grows_linearly_with_the_text() -> None:
    chunker = FixedTokenChunker()
    small = best_of(3, words(20_000), chunker)
    large = best_of(3, words(160_000), chunker)  # 8x the text
    assert large / small < 20  # linear = 8, quadratic = 64


def test_one_huge_word_is_one_token_and_fast() -> None:
    start = time.perf_counter()
    chunks = FixedTokenChunker().chunk(make_doc("a" * 2_000_000))
    assert len(chunks) == 1
    assert time.perf_counter() - start < 5
