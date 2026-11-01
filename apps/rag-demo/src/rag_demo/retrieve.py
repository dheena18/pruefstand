"""Hybrid retrieval: pure query builders and merge functions, plus the thin ``Retriever``."""

import logging
from collections import defaultdict
from typing import Any

import httpx

from rag_demo.analysis import GermanAnalyzer
from rag_demo.errors import RetrievalError
from rag_demo.models import Hit, QueryVectors, RagConfig, SparseVector
from rag_demo.protocols import DenseEncoder
from rag_demo.sparse import SparseEncoder

_log = logging.getLogger(__name__)
SHARED = "shared_public"
RRF_K = 60


def _filter(tenant_id: str) -> dict[str, Any]:
    tenants = sorted({tenant_id, SHARED})
    return {"must": [{"key": "tenant_id", "match": {"any": tenants}}]}


def _prefetch(
    vectors: QueryVectors, limit: int, flt: dict[str, Any] | None
) -> list[dict[str, Any]]:
    sparse: SparseVector = vectors.sparse
    legs: list[dict[str, Any]] = [
        {"query": vectors.dense, "using": "dense", "limit": limit},
        {
            "query": {"indices": sparse.indices, "values": sparse.values},
            "using": "sparse",
            "limit": limit,
        },
    ]
    if flt is not None:
        for leg in legs:
            leg["filter"] = flt
    return legs


def _body(prefetch: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {"prefetch": prefetch, "query": {"fusion": "rrf"}, "limit": limit, "with_payload": True}


def build_query(tenant_id: str, vectors: QueryVectors, cfg: RagConfig) -> dict[str, Any]:
    """Build the Qdrant Query API body (dense + sparse prefetch, RRF fusion).

    With ``tenant_filter: inside`` the filter ``tenant_id in {tenant, shared_public}`` sits in
    **every** prefetch. With ``post_topk`` (the M8 bug) no filter is sent at all.

    Args:
        tenant_id: The calling tenant.
        vectors: Query embeddings.
        cfg: Active configuration.

    Returns:
        JSON body for ``POST /collections/<c>/points/query``.
    """
    flt = _filter(tenant_id) if cfg.tenant_filter == "inside" else None
    return _body(_prefetch(vectors, max(20, cfg.top_k * 4), flt), cfg.top_k)


def build_shared_query(vectors: QueryVectors, cfg: RagConfig) -> dict[str, Any] | None:
    """Build the second query that merges ``shared_public`` hits, or ``None``.

    The correct mode (``filtered``) needs no second query: the main query already includes
    ``shared_public``. With ``unfiltered`` (the M9 bug) a second query without any tenant filter
    is sent and its hits are merged in.
    """
    if cfg.shared_public_merge == "filtered":
        return None
    return _body(_prefetch(vectors, max(20, cfg.top_k * 4), None), cfg.top_k)


def merge_rrf(lists: list[list[Hit]], top_k: int) -> list[Hit]:
    """Fuse ranked hit lists by reciprocal rank (k = 60); ranks are renumbered 1..n.

    Examples:
        >>> merge_rrf([], 3)
        []
    """
    score: dict[str, float] = defaultdict(float)
    first: dict[str, Hit] = {}
    for hits in lists:
        for hit in hits:
            score[hit.chunk_id] += 1.0 / (RRF_K + hit.rank)
            first.setdefault(hit.chunk_id, hit)
    order = sorted(score, key=lambda cid: -score[cid])[:top_k]
    return [
        first[cid].model_copy(update={"rank": i, "score": score[cid]})
        for i, cid in enumerate(order, start=1)
    ]


def apply_post_topk(hits: list[Hit], tenant_id: str, top_k: int) -> list[Hit]:
    """The classic M8 bug: filter by tenant **after** the top-k cut, then backfill.

    Hits of other tenants are dropped from the cut list, and when fewer than ``top_k`` remain the
    list is refilled from the unfiltered one, so foreign chunks come back at the end.
    """
    allowed = {tenant_id, SHARED}
    kept = [h for h in hits if h.tenant_id in allowed]
    if len(kept) < top_k:
        kept += [h for h in hits if h.tenant_id not in allowed]
    return [h.model_copy(update={"rank": i}) for i, h in enumerate(kept[:top_k], start=1)]


def to_hits(points: list[dict[str, Any]]) -> list[Hit]:
    """Map Qdrant scored points (with payload) to ranked hits."""
    out = []
    for rank, point in enumerate(points, start=1):
        p = point["payload"]
        out.append(
            Hit(
                chunk_id=p["chunk_id"],
                doc_id=p["doc_id"],
                tenant_id=p["tenant_id"],
                text=p["text"],
                score=float(point["score"]),
                rank=rank,
                citation_key=p.get("citation_key"),
                section=p.get("section"),
            )
        )
    return out


class Retriever:
    """Embed the query and ask Qdrant (thin wrapper around the pure builders above).

    Args:
        cfg: Active configuration (bug switches included).
        qdrant_url: Qdrant REST base URL.
        dense: Query encoder (TEI).
        analyzer: Tokeniser.
        sparse: Sparse encoder.
        collection: Collection name.
        client: Optional ``httpx.Client`` (tests record the requests through its transport).
    """

    def __init__(
        self,
        cfg: RagConfig,
        qdrant_url: str,
        dense: DenseEncoder,
        analyzer: GermanAnalyzer,
        sparse: SparseEncoder,
        *,
        collection: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._cfg = cfg
        self._url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/query"
        self._dense = dense
        self._analyzer = analyzer
        self._sparse = sparse
        self._client = client or httpx.Client(timeout=30)

    def retrieve(self, tenant_id: str, query: str, top_k: int) -> list[Hit]:
        """Return the top ``top_k`` chunks for ``tenant_id`` in rank order.

        Args:
            tenant_id: Caller's tenant (must be a known tenant; the API checks).
            query: The question.
            top_k: Number of chunks to return.

        Returns:
            Hits ranked 1..n.

        Raises:
            RetrievalError: Qdrant unreachable or answered with an error.
            EmbeddingError: The query could not be embedded.
        """
        cfg = self._cfg.model_copy(update={"top_k": top_k})
        vectors = QueryVectors(
            dense=self._dense.encode([query], kind="query")[0].tolist(),
            sparse=self._sparse.encode_query(self._analyzer.tokens(query)),
        )
        bodies = [build_query(tenant_id, vectors, cfg)]
        if (shared := build_shared_query(vectors, cfg)) is not None:
            bodies.append(shared)
        results = [to_hits(self._query(b)) for b in bodies]
        if cfg.tenant_filter == "post_topk":
            return apply_post_topk(merge_rrf(results, top_k), tenant_id, top_k)
        return merge_rrf(results, top_k) if len(results) > 1 else results[0]

    def _query(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.HTTPError as err:
            msg = f"qdrant unreachable ({type(err).__name__})"
            raise RetrievalError(msg) from None
        if resp.status_code != 200:
            msg = f"qdrant query returned HTTP {resp.status_code}"
            raise RetrievalError(msg)
        points: list[dict[str, Any]] = resp.json()["result"]["points"]
        return points
