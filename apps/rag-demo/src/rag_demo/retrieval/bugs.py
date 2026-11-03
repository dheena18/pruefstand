"""The seeded retrieval bugs M8 (``post_topk``) and M9 (``shared_public_merge: unfiltered``).

They are deliberate, stay available, and the safe behaviour is the default. The post-condition
guard of the retriever is skipped while one of them is active: they exist to produce real leaks
that the gate must catch (T1.11/T1.12 scenarios).
"""

from rag_demo.models import Hit, QueryVectors, RagConfig
from rag_demo.retrieval.filters import SHARED
from rag_demo.retrieval.query_builder import QdrantQuery, RrfFusion, RrfParams, legs


def leak_bug_active(cfg: RagConfig) -> bool:
    """True when ``tenant_filter`` or ``shared_public_merge`` is switched to its buggy value."""
    return cfg.tenant_filter != "inside" or cfg.shared_public_merge != "filtered"


def build_shared_query(vectors: QueryVectors, cfg: RagConfig, limit: int) -> QdrantQuery | None:
    """The second query that merges ``shared_public`` hits, or ``None``.

    The correct mode (``filtered``) needs no second query: the main query already includes
    ``shared_public``. With ``unfiltered`` (the M9 bug) a second query without any tenant filter
    is sent and its hits are merged in.
    """
    if cfg.shared_public_merge == "filtered":
        return None
    return QdrantQuery(
        prefetch=legs(vectors, cfg, None),
        query=RrfFusion(rrf=RrfParams(k=cfg.retrieval.rrf_k)),
        limit=limit,
    )


def merge_by_score(lists: list[list[Hit]], top_k: int) -> list[Hit]:
    """Merge hit lists of two queries by their scores (best score per chunk); ranks become 1..n.

    The score of a Qdrant RRF result is the fused score of its own query, so the best hits of
    each list compete on equal terms. This is how the second, unfiltered ``shared_public`` query
    of the M9 bug gets its top chunk into the answer.

    Examples:
        >>> merge_by_score([], 3)
        []
    """
    best: dict[str, Hit] = {}
    for hits in lists:
        for hit in hits:
            known = best.get(hit.chunk_id)
            if known is None or hit.score > known.score:
                best[hit.chunk_id] = hit
    ordered = sorted(best.values(), key=lambda h: -h.score)[:top_k]
    return [h.model_copy(update={"rank": i}) for i, h in enumerate(ordered, start=1)]


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
