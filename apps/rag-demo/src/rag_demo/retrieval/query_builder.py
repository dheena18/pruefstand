"""``build_query``: the single place that turns query vectors into a Qdrant Query API request.

Pure, no I/O. With ``tenant_filter: inside`` every prefetch leg and the top-level query carry the
tenant filter (defence in depth). ``post_topk`` (bug M8) sends no filter at all; the second,
unfiltered query of the M9 bug lives in ``bugs.py``.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from rag_demo.errors import RetrievalError
from rag_demo.models import Hit, QueryVectors, RagConfig
from rag_demo.retrieval.filters import Filter, tenant_filter


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SparseQuery(_Frozen):
    """A sparse query vector."""

    indices: list[int]
    values: list[float]


class Prefetch(_Frozen):
    """One retrieval leg (``using`` names the vector); ``filter`` is the tenant filter."""

    query: list[float] | SparseQuery
    using: Literal["dense", "sparse"]
    limit: int
    filter: Filter | None = None


class RrfParams(_Frozen):
    """Reciprocal rank fusion constant."""

    k: int


class RrfFusion(_Frozen):
    """Qdrant ``query: {rrf: {k}}``."""

    rrf: RrfParams


class QdrantQuery(_Frozen):
    """The body of ``POST /collections/<c>/points/query``."""

    prefetch: tuple[Prefetch, ...]
    query: RrfFusion
    filter: Filter | None = None
    limit: int
    with_payload: bool = True

    def to_json(self) -> dict[str, object]:
        """The JSON body (unset filters are left out)."""
        return self.model_dump(mode="json", exclude_none=True)


def legs(vectors: QueryVectors, cfg: RagConfig, flt: Filter | None) -> tuple[Prefetch, ...]:
    """The prefetch legs: dense, plus sparse when ``retrieval.hybrid`` is on."""
    limit = cfg.retrieval.prefetch_k
    out = [Prefetch(query=vectors.dense, using="dense", limit=limit, filter=flt)]
    if cfg.retrieval.hybrid:
        sparse = SparseQuery(indices=vectors.sparse.indices, values=vectors.sparse.values)
        out.append(Prefetch(query=sparse, using="sparse", limit=limit, filter=flt))
    return tuple(out)


def build_query(
    tenant_id: str, vectors: QueryVectors, cfg: RagConfig, *, limit: int | None = None
) -> QdrantQuery:
    """Build the hybrid Query API request (dense + sparse prefetch, RRF).

    Args:
        tenant_id: The calling tenant.
        vectors: Query embeddings (the sparse part is ignored when ``retrieval.hybrid`` is off).
        cfg: Active configuration (bug switches included).
        limit: Number of fused hits to return (default ``cfg.top_k``).

    Returns:
        The request. With ``tenant_filter: inside`` each prefetch and the query carry the filter;
        with ``post_topk`` (the M8 bug) none does.

    Raises:
        ValueError: Unknown tenant.
    """
    flt = tenant_filter(tenant_id) if cfg.tenant_filter == "inside" else None
    return QdrantQuery(
        prefetch=legs(vectors, cfg, flt),
        query=RrfFusion(rrf=RrfParams(k=cfg.retrieval.rrf_k)),
        filter=flt,
        limit=limit or cfg.top_k,
    )


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str
    tenant_id: str
    text: str
    citation_key: str | None = None
    section: str | None = None
    lang: str | None = None


class _Point(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: float
    payload: _Payload


def to_hits(points: Sequence[object]) -> list[Hit]:
    """Map the ``points`` of a Qdrant query answer (with payload) to hits ranked 1..n.

    Raises:
        RetrievalError: The answer is not a list of scored points with the expected payload.
    """
    try:
        parsed = [_Point.model_validate(p) for p in points]
    except (ValidationError, TypeError):
        msg = "qdrant answered with an unexpected point shape"
        raise RetrievalError(msg) from None
    return [Hit(rank=i, score=p.score, **p.payload.model_dump()) for i, p in enumerate(parsed, 1)]
