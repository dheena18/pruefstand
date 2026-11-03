"""``QdrantRetriever``: embed the query, one Qdrant Query API call, optional rerank, top-k.

The tenant filter is built in ``filters.tenant_filter`` and reaches Qdrant only through
``query_builder.build_query`` (inside every prefetch, never a post-filter). The post-condition
guard is a safety net on top of that.
"""

import logging

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.errors import TenantIsolationError
from rag_demo.models import Hit, QueryVectors, RagConfig, SparseVector
from rag_demo.protocols import DenseEncoder, Reranker
from rag_demo.retrieval.bugs import (
    apply_post_topk,
    build_shared_query,
    leak_bug_active,
    merge_by_score,
)
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.filters import allowed_tenants
from rag_demo.retrieval.query_builder import QdrantQuery, build_query, to_hits
from rag_demo.retrieval.rerank import renumber
from rag_demo.retrieval.store import QdrantStore

_log = logging.getLogger(__name__)


class QdrantRetriever:
    """Hybrid retrieval for one tenant (interfaces §16 ``Retriever``).

    Args:
        cfg: Active configuration (bug switches included).
        store: The Qdrant client of the served collection (alias ``chunks_active``).
        corpus: Checked collection metadata; a stale or differently analysed index is refused.
        dense: Query encoder.
        analyzer: Tokeniser (the one the index was built with, checked by ``corpus``).
        sparse: Sparse encoder.
        reranker: ``IdentityReranker`` or ``CrossEncoderReranker``.
        guard: Post-condition guard on (default); tests also run with it off to prove the filter.
    """

    def __init__(
        self,
        cfg: RagConfig,
        *,
        store: QdrantStore,
        corpus: CorpusMeta,
        dense: DenseEncoder,
        analyzer: GermanAnalyzer,
        sparse: SparseEncoder,
        reranker: Reranker,
        guard: bool = True,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._corpus = corpus
        self._dense = dense
        self._analyzer = analyzer
        self._sparse = sparse
        self._reranker = reranker
        self._guard = guard

    def with_reranker(self, reranker: Reranker) -> "QdrantRetriever":
        """A retriever that shares everything with this one but the reranker."""
        return QdrantRetriever(
            self._cfg,
            store=self._store,
            corpus=self._corpus,
            dense=self._dense,
            analyzer=self._analyzer,
            sparse=self._sparse,
            reranker=reranker,
            guard=self._guard,
        )

    def retrieve(self, tenant_id: str, query: str, top_k: int) -> list[Hit]:
        """Return the top ``top_k`` chunks for ``tenant_id`` in rank order.

        Args:
            tenant_id: Caller's tenant (the API checks that it exists in the index).
            query: The question.
            top_k: Number of chunks to return.

        Returns:
            Hits ranked 1..n (at most ``top_k``), tenant filter applied inside the search.

        Raises:
            ValueError: Malformed tenant id.
            IndexUnavailableError: The index is unreadable or incomplete.
            IndexMismatchError: The index was built with another analyzer or hash scheme.
            RetrievalError: Qdrant unreachable or answered with an error.
            RerankError: The reranker failed.
            EmbeddingError: The query could not be embedded.
            TenantIsolationError: A hit of a foreign tenant came back (guard).
        """
        allowed = allowed_tenants(tenant_id)
        self._corpus.get()
        cfg = self._cfg.model_copy(update={"top_k": top_k})
        fused = self._first_stage(tenant_id, query, cfg)
        hits = renumber(self._reranker.rerank(query, fused, cfg.rerank.top_n)[:top_k])
        if self._guard and not leak_bug_active(cfg):
            self._check(hits, allowed, tenant_id)
        return hits

    def _vectors(self, query: str) -> QueryVectors:
        dense = self._dense.encode([query], kind="query")[0].tolist()
        if not self._cfg.retrieval.hybrid:
            return QueryVectors(dense=dense, sparse=SparseVector(indices=[], values=[]))
        sparse = self._sparse.encode_query(self._analyzer.tokens(query))
        return QueryVectors(dense=dense, sparse=sparse)

    def _first_stage(self, tenant_id: str, query: str, cfg: RagConfig) -> list[Hit]:
        top_k = cfg.top_k
        vectors = self._vectors(query)
        if cfg.tenant_filter == "post_topk":  # M8 bug: unfiltered query, cut, then Python filter
            requests = [build_query(tenant_id, vectors, cfg, limit=top_k)]
            merged = merge_by_score(self._run(requests, vectors, cfg, top_k), top_k)
            return apply_post_topk(merged, tenant_id, top_k)
        limit = max(top_k, cfg.rerank.top_n) if cfg.reranker == "on" else top_k
        requests = [build_query(tenant_id, vectors, cfg, limit=limit)]
        results = self._run(requests, vectors, cfg, limit)
        return merge_by_score(results, limit) if len(results) > 1 else results[0]

    def _run(
        self, requests: list[QdrantQuery], vectors: QueryVectors, cfg: RagConfig, limit: int
    ) -> list[list[Hit]]:
        if (shared := build_shared_query(vectors, cfg, limit)) is not None:  # M9 bug
            requests.append(shared)
        return [to_hits(self._store.query(r)) for r in requests]

    @staticmethod
    def _check(hits: list[Hit], allowed: frozenset[str], tenant_id: str) -> None:
        foreign = [h.chunk_id for h in hits if h.tenant_id not in allowed]
        if foreign:
            _log.error("tenant_isolation_violation tenant=%s chunks=%s", tenant_id, foreign)
            msg = "retrieval returned a chunk of a foreign tenant"
            raise TenantIsolationError(msg)
