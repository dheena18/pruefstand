"""Index fingerprint: a stale or differently analysed index is refused (T3.3 review, D461)."""

import pytest

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.fingerprint import check_fingerprint, fingerprint, index_metadata
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.errors import IndexMismatchError, RetrievalError

FULL = GermanAnalyzer(compound_split=True, stemmer="snowball_de")
SPARSE = SparseEncoder()


def test_fingerprint_names_hash_scheme_analyzer_flags_and_lexicon_digest() -> None:
    fp = fingerprint(FULL, SPARSE)
    assert fp["scheme"] == "xxhash64-mod-dim"
    assert fp["dim"] == 2**31
    assert (fp["compound_split"], fp["stemmer"], fp["fold_umlauts"]) == (True, "snowball_de", True)
    assert isinstance(fp["data_digest"], str)
    assert "avgdl" not in fp


def test_matching_fingerprint_is_accepted() -> None:
    check_fingerprint(fingerprint(FULL, SPARSE), fingerprint(FULL, SPARSE))


def test_index_without_fingerprint_is_refused_with_a_reindex_hint() -> None:
    """A slice_v1-style collection has no analyzer metadata at all."""
    with pytest.raises(IndexMismatchError, match="re-index"):
        check_fingerprint(None, fingerprint(FULL, SPARSE))


def test_differing_compound_split_is_refused_and_named() -> None:
    off = GermanAnalyzer(compound_split=False, stemmer="snowball_de")
    with pytest.raises(IndexMismatchError, match="compound_split") as err:
        check_fingerprint(fingerprint(off, SPARSE), fingerprint(FULL, SPARSE))
    assert isinstance(err.value, RetrievalError)


def test_differing_hash_dimension_is_refused() -> None:
    small = SparseEncoder(dim=1 << 20)
    with pytest.raises(IndexMismatchError, match="dim"):
        check_fingerprint(fingerprint(FULL, small), fingerprint(FULL, SPARSE))


def test_index_metadata_stores_avgdl_and_fingerprint() -> None:
    meta = index_metadata({"corpus_version": "v", "tenants": ["a"]}, FULL, SPARSE, 41.5)
    assert meta["avgdl"] == 41.5
    assert meta["analyzer"] == fingerprint(FULL, SPARSE)
    assert meta["corpus_version"] == "v"


def test_with_avg_len_keeps_every_other_setting() -> None:
    other = SPARSE.with_avg_len(10.0)
    assert (other.avg_len, other.dim, other.k1, other.b) == (10.0, SPARSE.dim, SPARSE.k1, SPARSE.b)
    assert fingerprint(FULL, other) == fingerprint(FULL, SPARSE)
