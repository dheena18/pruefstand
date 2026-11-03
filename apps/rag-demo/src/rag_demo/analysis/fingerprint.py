"""Index fingerprint: what the sparse leg of an index depends on (hash scheme, analyzer, data).

The Indexer writes it into the collection metadata; the app compares it with its own analyzer
before it answers a query and refuses a mismatch, because querying an index with a different
hash scheme or analyzer silently degrades to dense-only retrieval.
"""

import hashlib
from importlib import resources
from typing import Any

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.errors import IndexMismatchError

HASH_SCHEME = "xxhash64-mod-dim"


def _data_digest() -> str:
    """First 12 hex of sha256 over the shipped lexicon and stopword files."""
    digest = hashlib.sha256()
    for name in ("lexicon_de.txt", "stopwords_de.txt"):
        digest.update((resources.files("rag_demo.analysis") / name).read_bytes())
    return digest.hexdigest()[:12]


def fingerprint(analyzer: GermanAnalyzer, sparse: SparseEncoder) -> dict[str, Any]:
    """Return the settings the index contents depend on (``avgdl`` is stored separately).

    Args:
        analyzer: The analyzer used at index and query time.
        sparse: The sparse encoder (hash scheme, dimension, BM25 constants).

    Returns:
        A JSON-serialisable dict; equal dicts mean a compatible index.
    """
    return {
        "scheme": HASH_SCHEME,
        "dim": sparse.dim,
        "k1": sparse.k1,
        "b": sparse.b,
        "compound_split": analyzer.compound_split,
        "stemmer": analyzer.stemmer,
        "fold_umlauts": analyzer.fold_umlauts,
        "data_digest": _data_digest(),
    }


def index_metadata(
    manifest: dict[str, Any], analyzer: GermanAnalyzer, sparse: SparseEncoder, avgdl: float
) -> dict[str, Any]:
    """Collection metadata: corpus version, tenants, analyzer fingerprint and the average length."""
    return {
        "corpus_version": manifest["corpus_version"],
        "tenants": sorted(manifest["tenants"]),
        "analyzer": fingerprint(analyzer, sparse),
        "avgdl": avgdl,
    }


def check_fingerprint(stored: object, expected: dict[str, Any]) -> None:
    """Raise if the stored fingerprint is missing or differs from ``expected``.

    Raises:
        IndexMismatchError: Names the differing keys and asks for a re-index.
    """
    if not isinstance(stored, dict):
        msg = "index has no analyzer fingerprint (built before T3.3); re-index"
        raise IndexMismatchError(msg)
    keys = sorted(k for k in expected.keys() | stored.keys() if stored.get(k) != expected.get(k))
    if keys:
        msg = f"index was built with another analyzer or hash scheme ({', '.join(keys)}); re-index"
        raise IndexMismatchError(msg)
