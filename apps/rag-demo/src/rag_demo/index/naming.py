"""Collection names: the index fingerprint ``chunks__<corpus>__<analyzer_hash8>__<embed_slug>``."""

import hashlib
import json
import re

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.models import ChunkingCfg

ALIAS = "chunks_active"


def slug(text: str) -> str:
    """Lower-case ``text`` and replace every run of other characters by one dash.

    Examples:
        >>> slug("intfloat/multilingual-e5-small")
        'intfloat-multilingual-e5-small'
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def analyzer_hash(analyzer: GermanAnalyzer, sparse: SparseEncoder) -> str:
    """First 8 hex of sha256 over the analyzer fingerprint (T3.3), so it keys the collection."""
    canonical = json.dumps(fingerprint(analyzer, sparse), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def collection_name(
    corpus_version: str, analyzer_hash8: str, embed_model: str, chunking: str = ""
) -> str:
    """The index-fingerprint collection name; any change of corpus, analyzer or model renames it.

    Examples:
        >>> collection_name("2026-11-03.abcd1234", "0123abcd", "BAAI/bge-m3")
        'chunks__2026-11-03-abcd1234__0123abcd__baai-bge-m3'
        >>> collection_name("v", "0123abcd", "m", "ft512")
        'chunks__v__0123abcd__m__ft512'
    """
    base = f"chunks__{slug(corpus_version)}__{analyzer_hash8}__{slug(embed_model)}"
    return f"{base}__{chunking}" if chunking else base


def build_name(base: str, build_id: str) -> str:
    """The name of one build: every build gets a fresh collection, the alias moves afterwards.

    Examples:
        >>> build_name("chunks__v__h__m", "ab12cd34")
        'chunks__v__h__m__bab12cd34'
    """
    return f"{base}__b{build_id}"


def chunking_metadata(chunking: ChunkingCfg) -> dict[str, object]:
    """The chunking as stored in the collection metadata (``{"strategy": ..., "size": ...}``)."""
    return {"strategy": chunking.strategy, "size": chunking.size}


def chunking_slug(chunking: ChunkingCfg) -> str:
    """Name part of a non-default chunking (``ft512``); empty for ``per_section``.

    Examples:
        >>> chunking_slug(ChunkingCfg(strategy="fixed_tokens", size=512))
        'ft512'
        >>> chunking_slug(ChunkingCfg())
        ''
    """
    return f"ft{chunking.size}" if chunking.strategy == "fixed_tokens" else ""
