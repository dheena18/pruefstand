"""``Indexer``: one Qdrant collection per index fingerprint, switched in by an atomic alias."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.fingerprint import index_metadata
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.errors import IndexMismatchError
from rag_demo.index.corpus_reader import index_text, point_id, read_corpus
from rag_demo.index.naming import ALIAS, analyzer_hash, collection_name
from rag_demo.index.qdrant_admin import QdrantAdmin
from rag_demo.models import SparseVector
from rag_demo.protocols import DenseEncoder

_log = logging.getLogger(__name__)
BATCH = 32


@dataclass(frozen=True)
class IndexTarget:
    """Where the index goes.

    Attributes:
        embed_model: Embedding model name (part of the default collection name).
        collection: Explicit collection name (PR-scoped ``pr_<N>_<shortsha>``); ``None`` derives
            ``chunks__<corpus>__<analyzer_hash8>__<embed_slug>``.
        alias: Alias to switch to the new collection after the full build; ``None`` = never
            touch aliases (``--no-alias``; PR jobs never write ``chunks_active``).
    """

    embed_model: str
    collection: str | None = None
    alias: str | None = ALIAS


@dataclass(frozen=True)
class IndexReport:
    """What one ``Indexer.index`` run did."""

    collection: str
    corpus_version: str
    chunks: int
    truncated_chunks: int
    alias: str | None
    alias_switched: bool


def alias_actions(alias: str, current: str | None, target: str) -> list[dict[str, Any]]:
    """The alias actions of one atomic switch (delete the old alias, create it on ``target``)."""
    actions: list[dict[str, Any]] = []
    if current is not None:
        actions.append({"delete_alias": {"alias_name": alias}})
    actions.append({"create_alias": {"collection_name": target, "alias_name": alias}})
    return actions


def build_point(row: dict[str, Any], dense: list[float], sparse: SparseVector) -> dict[str, Any]:
    """One Qdrant point: UUID5 id, named vectors ``dense`` / ``sparse`` and the payload."""
    return {
        "id": point_id(row["chunk_id"]),
        "vector": {
            "dense": dense,
            "sparse": {"indices": sparse.indices, "values": sparse.values},
        },
        "payload": {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "tenant_id": row["tenant"],
            "citation_key": row["citation_key"],
            "section": row["section"],
            "lang": row["lang"],
            "text": row["text"],
            "source": row["source"],
            "is_attack": row["is_attack"],
            "version_date": row["version_date"],
        },
    }


class Indexer:
    """Build (or idempotently refresh) the collection of a corpus and switch the alias.

    Args:
        qdrant_url: Qdrant REST base URL.
        dense: Passage encoder.
        analyzer: Tokeniser for the sparse leg (built from ``cfg.analyzer``).
        sparse: Sparse encoder.
        target: Collection name, alias and embedding model name.
        client: Optional ``httpx.Client`` (tests).
        api_key: Optional Qdrant API key.

    Attributes:
        last_report: The result of the last ``index`` call.
    """

    def __init__(
        self,
        qdrant_url: str,
        dense: DenseEncoder,
        analyzer: GermanAnalyzer,
        sparse: SparseEncoder,
        *,
        target: IndexTarget,
        client: httpx.Client | None = None,
        api_key: str | None = None,
    ) -> None:
        self._admin = QdrantAdmin(qdrant_url, api_key=api_key, client=client)
        self._dense = dense
        self._analyzer = analyzer
        self._sparse = sparse
        self._target = target
        self.last_report: IndexReport | None = None

    def index(self, corpus_dir: Path) -> None:
        """Embed the corpus and write it into one collection; switch the alias when complete.

        A re-run with the same corpus upserts the same point ids (no duplicates), removes points
        that are no longer in the corpus and leaves the alias where it is.

        Args:
            corpus_dir: Directory with ``manifest.json`` and ``<tenant>.chunks.jsonl`` files.

        Raises:
            CorpusError: Invalid corpus files.
            EncoderError: The embedding service failed.
            IndexMismatchError: The collection exists with another dense dimension.
            RetrievalError: Qdrant refused a request.
        """
        manifest, rows = read_corpus(corpus_dir)
        tokens = [self._analyzer.tokens(index_text(r)) for r in rows]
        avgdl = sum(map(len, tokens)) / max(len(rows), 1)
        sparse = self._sparse.with_avg_len(avgdl)
        cut_before = self._dense.truncated
        dim = int(self._dense.encode(["dim probe"], kind="passage").shape[1])
        name = self._target.collection or collection_name(
            manifest["corpus_version"],
            analyzer_hash(self._analyzer, sparse),
            self._target.embed_model,
        )
        metadata = {
            **index_metadata(manifest, self._analyzer, sparse, avgdl),
            "embed_model": self._target.embed_model,
            "dim": dim,
            "truncated_chunks": 0,
        }
        existed = self._prepare(name, dim, metadata)
        for start in range(0, len(rows), BATCH):
            end = start + BATCH
            self._upsert(name, rows[start:end], tokens[start:end], sparse)
        if existed:
            self._admin.prune(name, [point_id(r["chunk_id"]) for r in rows])
        cut = self._dense.truncated - cut_before
        self._admin.set_metadata(name, {**metadata, "truncated_chunks": cut})
        switched = self._switch(name)
        self.last_report = IndexReport(
            name, manifest["corpus_version"], len(rows), cut, self._target.alias, switched
        )
        _log.info("indexed chunks=%d collection=%s truncated=%d", len(rows), name, cut)

    def _prepare(self, name: str, dim: int, metadata: dict[str, Any]) -> bool:
        info = self._admin.collection_info(name)
        if info is None:
            self._admin.create_collection(name, dim, metadata)
        else:
            size = info["config"]["params"]["vectors"]["dense"]["size"]
            if size != dim:
                msg = f"collection {name} has dense size {size}, the encoder makes {dim}; drop it"
                raise IndexMismatchError(msg)
        self._admin.ensure_payload_indexes(name)
        return info is not None

    def _upsert(
        self,
        name: str,
        rows: list[dict[str, Any]],
        tokens: list[list[str]],
        sparse: SparseEncoder,
    ) -> None:
        vectors = self._dense.encode([index_text(r) for r in rows], kind="passage")
        points = [
            build_point(row, vector.tolist(), sparse.encode(toks))
            for row, toks, vector in zip(rows, tokens, vectors, strict=True)
        ]
        self._admin.upsert(name, points)

    def _switch(self, name: str) -> bool:
        alias = self._target.alias
        if alias is None:
            return False
        current = self._admin.alias_target(alias)
        if current == name:
            return False
        self._admin.apply_aliases(alias_actions(alias, current, name))
        return True
