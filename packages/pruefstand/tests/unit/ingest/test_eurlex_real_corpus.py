"""All 20 pinned EUR-Lex acts, DE and EN, real data from `make data` (T2.4). Marker `network`."""

from pathlib import Path

import pytest
from pruefstand.ingest.align import chunk_aligned
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.eurlex import EurLexLoader

from pruefstand.core.citations import extract_citations, normalise
from pruefstand.core.models.corpus import Chunk, Document

RAW = Path(__file__).resolve().parents[5] / "data" / "raw" / "eurlex"
pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(not RAW.is_dir(), reason="run `make data` first (data/raw/eurlex missing)"),
]
Pairs = list[tuple[Chunk, Chunk]]


@pytest.fixture(scope="module")
def corpus() -> tuple[EurLexLoader, list[Document], Pairs]:
    loader = EurLexLoader()
    docs = list(loader.load(RAW))
    chunker = ArticleChunker()
    pairs: Pairs = []
    for de, en in zip(docs[0::2], docs[1::2], strict=True):
        pairs.extend(zip(*chunk_aligned(chunker, de, en), strict=True))
    return loader, docs, pairs


def test_twenty_acts_two_languages_no_problems(
    corpus: tuple[EurLexLoader, list[Document], Pairs],
) -> None:
    loader, docs, _ = corpus
    assert len(docs) == 40
    assert loader.stats.problems == []
    assert loader.stats.misaligned_acts == 0
    assert {d.metadata["celex"] for d in docs}
    assert len({d.doc_id for d in docs}) == 40


def test_at_least_1500_aligned_pairs(corpus: tuple[EurLexLoader, list[Document], Pairs]) -> None:
    assert len(corpus[2]) >= 1500


def test_gdpr_article_6_pair(corpus: tuple[EurLexLoader, list[Document], Pairs]) -> None:
    pair = {de.parallel_id: (de, en) for de, en in corpus[2]}["32016R0679:art-6"]
    assert "Rechtmäßigkeit der Verarbeitung" in pair[0].text
    assert "Lawfulness of processing" in pair[1].text
    assert pair[0].citation_key == pair[1].citation_key == "Art. 6 DSGVO"


def test_every_article_key_round_trips(corpus: tuple[EurLexLoader, list[Document], Pairs]) -> None:
    keys = {c.citation_key for pair in corpus[2] for c in pair if c.citation_key}
    assert keys
    for key in keys:
        assert normalise(extract_citations(key)[0]) == key


def test_no_article_text_is_empty_or_carries_markers(
    corpus: tuple[EurLexLoader, list[Document], Pairs],
) -> None:
    for de, en in corpus[2]:
        for chunk in (de, en):
            assert len(chunk.text.split()) >= 4
            assert "\x1e" not in chunk.text
