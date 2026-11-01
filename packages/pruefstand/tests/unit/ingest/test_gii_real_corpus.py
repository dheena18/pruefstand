"""All 30 pinned GII laws, real data from `make data` (T2.2). Marker `network`."""

import resource
import unicodedata
from pathlib import Path

import pytest

from pruefstand.core.citations import extract_citations, normalise
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii_xml import GiiXmlLoader

RAW = Path(__file__).resolve().parents[5] / "data" / "raw" / "gii"
pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(not RAW.is_dir(), reason="run `make data` first (data/raw/gii missing)"),
]


@pytest.fixture(scope="module")
def corpus() -> tuple[GiiXmlLoader, list[Document], list[Chunk]]:
    loader = GiiXmlLoader()
    docs = list(loader.load(RAW))
    chunker = ParagraphChunker()
    return loader, docs, [c for d in docs for c in chunker.chunk(d)]


def test_all_thirty_laws_load_without_errors(
    corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]],
) -> None:
    loader, docs, _ = corpus
    assert len(loader.stats.laws) == 30
    assert loader.stats.error_count == 0, loader.stats.problems[:5]
    assert all(law.documents > 0 for law in loader.stats.laws.values())
    assert all(law.version_date is not None for law in loader.stats.laws.values())
    assert len({d.doc_id for d in docs}) == len(docs)


def test_bgb_has_at_least_2000_chunks(
    corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]],
) -> None:
    _, _, chunks = corpus
    assert sum(1 for c in chunks if c.doc_id.startswith("gii-bgb-")) >= 2000


def test_known_norms_are_present(corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]]) -> None:
    _, docs, _ = corpus
    by_id = {str(d.doc_id): d for d in docs}
    assert by_id["gii-bgb-622"].metadata["citation_key"] == "§ 622 BGB"
    assert by_id["gii-kschg-1"].title == "Sozial ungerechtfertigte Kündigungen"
    assert by_id["gii-arbzg-3"].text.startswith("Die werktägliche Arbeitszeit")
    assert "gii-sgb-iv-1" in by_id
    assert "gii-egbgb-246a-1" in by_id


def test_every_chunk_is_well_formed(
    corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]],
) -> None:
    _, _, chunks = corpus
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    for chunk in chunks:
        assert chunk.text.strip()
        assert unicodedata.is_normalized("NFC", chunk.text)
        assert chunk.citation_key is not None
        (cite,) = extract_citations(chunk.citation_key)
        assert normalise(cite) == chunk.citation_key


def test_peak_memory_stays_below_500_mb(
    corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]],
) -> None:
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 500 * 1024  # KiB on Linux


def test_citation_keys_are_not_unique(
    corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]],
) -> None:
    """Nested EGBGB paragraphs share the key of their Artikel; split chunks share their § key."""
    _, _, chunks = corpus
    keys = [c.citation_key for c in chunks]
    assert len(set(keys)) < len(keys)
    assert keys.count("Art. 229 EGBGB") > 10


def test_totals_of_the_pinned_set(corpus: tuple[GiiXmlLoader, list[Document], list[Chunk]]) -> None:
    loader, docs, chunks = corpus
    skipped = {
        r: sum(law.skipped.get(r, 0) for law in loader.stats.laws.values())
        for r in ("placeholder", "uncitable")
    }
    assert skipped["uncitable"] == 0
    assert {"gii-kwg-53ca", "gii-kwg-53cq"} <= {str(d.doc_id) for d in docs}
    assert skipped["placeholder"] >= 14
    assert not [d for d in docs if d.text.strip() == "-"]
    assert not [c for c in chunks if c.text.strip() in ("(weggefallen)",)]
