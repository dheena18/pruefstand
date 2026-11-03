"""``QdrantRetriever`` plumbing against Qdrant's, TEI's and rerank-cpu's REST APIs (respx).

The behaviour on a real index (isolation, M8/M9, ranking) is in ``tests/integration``.
"""

import json
import logging

import httpx
import pytest
import respx
from rd_support import CONFIGS, qdrant_point

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.errors import IndexMismatchError, RerankError, TenantIsolationError
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.models import EmbedCfg, RagConfig, RerankCfg
from rag_demo.protocols import Reranker
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.rerank import CrossEncoderReranker, IdentityReranker
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.retrieval.store import QdrantStore
from rag_demo.retrieval.testing import assert_tenant_scoped
from rag_demo.wiring import build_analyzer, expected_fingerprint

BASE = "http://qdrant.test:6333"
COLL = f"{BASE}/collections/chunks_active"
TEI = "http://embed.test:8090"
RERANK = "http://rerank-cpu.test:8201"
GOOD = load_config(CONFIGS / "rag.yaml")
T = "kanzlei_mueller"
CHUNKS = ["gii-bgb-622#1", "gii-kschg-1#0", "gii-bgb-620#0", "gii-bgb-621#0"]


def _meta(cfg: RagConfig, **extra: object) -> httpx.Response:
    meta = {
        "corpus_version": "fixture-1",
        "tenants": [T, "shared_public"],
        "analyzer": expected_fingerprint(cfg),
        "complete": True,
        **extra,
    }
    return httpx.Response(200, json={"result": {"config": {"metadata": meta}}})


def _points(*ids: str) -> httpx.Response:
    points = [qdrant_point(cid, 0.3 - i * 0.01) for i, cid in enumerate(ids)]
    return httpx.Response(200, json={"result": {"points": points}})


def _retriever(
    cfg: RagConfig = GOOD,
    *,
    guard: bool = True,
    reranker: Reranker | None = None,
    api_key: str | None = None,
) -> QdrantRetriever:
    store = QdrantStore(BASE, "chunks_active", api_key=api_key)
    return QdrantRetriever(
        cfg,
        store=store,
        corpus=CorpusMeta(store, expected_fingerprint(cfg)),
        dense=TeiDenseEncoder(EmbedCfg(model="plain", dim=3), TEI),
        analyzer=build_analyzer(cfg),
        sparse=SparseEncoder(),
        reranker=reranker or IdentityReranker(),
        guard=guard,
    )


def _using(body: dict[str, object]) -> list[str]:
    prefetch = body["prefetch"]
    assert isinstance(prefetch, list)
    return [str(p["using"]) for p in prefetch]


def _bodies(route: respx.Route) -> list[dict[str, object]]:
    return [json.loads(c.request.content) for c in route.calls]


@respx.mock
def test_one_query_request_with_the_filter_in_every_prefetch_and_the_api_key() -> None:
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(GOOD))
    query = respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    hits = _retriever(api_key="k1").retrieve(T, "Welche Frist gilt?", 3)
    assert [h.rank for h in hits] == [1, 2, 3]
    assert [h.chunk_id for h in hits] == CHUNKS[:3]
    (body,) = _bodies(query)
    assert_tenant_scoped(body, T)
    assert body["limit"] == 3
    assert query.calls.last.request.headers["api-key"] == "k1"
    assert _using(body) == ["dense", "sparse"]


@respx.mock
def test_a_malformed_tenant_is_refused_before_any_request() -> None:
    with pytest.raises(ValueError, match="unknown tenant"):
        _retriever().retrieve("Kanzlei Mueller", "Frist", 3)


@respx.mock
def test_an_index_with_another_analyzer_is_refused_and_no_query_is_sent() -> None:
    other = GOOD.model_copy(
        update={"analyzer": GOOD.analyzer.model_copy(update={"compound_split": False})}
    )
    respx.get(COLL).mock(return_value=_meta(other))
    query = respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    with pytest.raises(IndexMismatchError, match="compound_split"):
        _retriever().retrieve(T, "Frist", 3)
    assert query.call_count == 0


@respx.mock
def test_dense_only_mode_sends_one_filtered_prefetch_and_no_sparse_encoding() -> None:
    cfg = GOOD.model_copy(update={"retrieval": GOOD.retrieval.model_copy(update={"hybrid": False})})
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    query = respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    _retriever(cfg).retrieve(T, "Frist", 4)
    (body,) = _bodies(query)
    assert _using(body) == ["dense"]
    assert_tenant_scoped(body, T)


def _foreign_stack(cfg: RagConfig) -> respx.Route:
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    return respx.post(f"{COLL}/points/query").mock(
        return_value=_points("syn-vn-rahmenvertrag-bergmann#0", "gii-bgb-622#1")
    )


@respx.mock
def test_the_guard_refuses_a_foreign_chunk_and_logs_at_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _foreign_stack(GOOD)
    with caplog.at_level(logging.ERROR), pytest.raises(TenantIsolationError):
        _retriever().retrieve(T, "Bergmann", 2)
    assert any(
        r.levelno == logging.ERROR and "versicherung" not in r.message for r in caplog.records
    )
    assert any("syn-vn-rahmenvertrag-bergmann#0" in r.message for r in caplog.records)


@respx.mock
def test_with_the_guard_off_the_answer_is_passed_through() -> None:
    _foreign_stack(GOOD)
    hits = _retriever(guard=False).retrieve(T, "Bergmann", 2)
    assert hits[0].tenant_id == "versicherung_nord"


@respx.mock
def test_the_guard_is_skipped_while_a_leak_bug_switch_is_active() -> None:
    cfg = load_config(CONFIGS / "bugs" / "shared_public_unfiltered.yaml")
    route = _foreign_stack(cfg)
    hits = _retriever(cfg).retrieve(T, "Bergmann", 2)
    assert any(h.tenant_id == "versicherung_nord" for h in hits)
    bodies = _bodies(route)
    assert len(bodies) == 2  # the main query and the second, unfiltered shared_public query
    assert "filter" not in bodies[1]


@respx.mock
def test_post_topk_sends_no_filter_and_drops_foreign_chunks_after_the_cut() -> None:
    cfg = load_config(CONFIGS / "bugs" / "tenant_filter_post_topk.yaml")
    route = _foreign_stack(cfg)
    hits = _retriever(cfg).retrieve(T, "Bergmann", 2)
    (body,) = _bodies(route)
    assert "filter" not in body
    assert [h.tenant_id for h in hits] == ["shared_public", "versicherung_nord"]  # backfilled
    assert [h.rank for h in hits] == [1, 2]


def _rerank_cfg(top_n: int) -> RagConfig:
    return GOOD.model_copy(update={"reranker": "on", "rerank": RerankCfg(top_n=top_n)})


def _reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker(RERANK, max_passage_tokens=256, timeout_s=5.0)


@respx.mock
def test_the_reranker_scores_the_top_n_in_one_request_and_the_query_asks_for_enough() -> None:
    cfg = _rerank_cfg(3)
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    query = respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    rerank = respx.post(f"{RERANK}/rerank").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.5},
                {"index": 1, "score": 0.1},
            ],
        )
    )
    hits = _retriever(cfg, reranker=_reranker()).retrieve(T, "Frist", 2)
    assert _bodies(query)[0]["limit"] == 3  # max(top_k, rerank.top_n)
    assert rerank.call_count == 1
    assert len(json.loads(rerank.calls.last.request.content)["texts"]) == 3
    assert [h.chunk_id for h in hits] == ["gii-bgb-620#0", "gii-bgb-622#1"]
    assert [h.score for h in hits] == [0.9, 0.5]
    assert [h.rank for h in hits] == [1, 2]


@respx.mock
def test_a_top_k_above_top_n_reranks_all_returned_hits_so_scores_are_not_mixed() -> None:
    cfg = _rerank_cfg(2)
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    query = respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    scores = [{"index": 2, "score": 0.8}, {"index": 1, "score": 0.5}, {"index": 0, "score": 0.2}]
    rerank = respx.post(f"{RERANK}/rerank").mock(return_value=httpx.Response(200, json=scores))
    hits = _retriever(cfg, reranker=_reranker()).retrieve(T, "Frist", 3)
    assert _bodies(query)[0]["limit"] == 3
    assert len(json.loads(rerank.calls.last.request.content)["texts"]) == 3
    assert [h.chunk_id for h in hits] == ["gii-bgb-620#0", "gii-kschg-1#0", "gii-bgb-622#1"]
    assert [h.score for h in hits] == [0.8, 0.5, 0.2]  # all reranker scores
    assert [h.rank for h in hits] == [1, 2, 3]


@respx.mock
def test_with_the_identity_reranker_the_rerank_service_is_never_called() -> None:
    cfg = _rerank_cfg(3)
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    rerank = respx.post(f"{RERANK}/rerank").mock(return_value=httpx.Response(500))
    retriever = _retriever(cfg, reranker=_reranker()).with_reranker(IdentityReranker())
    hits = retriever.retrieve(T, "Frist", 2)
    assert [h.chunk_id for h in hits] == CHUNKS[:2]
    assert rerank.call_count == 0


@respx.mock
def test_a_failing_reranker_fails_the_retrieval_instead_of_degrading_silently() -> None:
    cfg = _rerank_cfg(3)
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2, 0.3]]))
    respx.get(COLL).mock(return_value=_meta(cfg))
    respx.post(f"{COLL}/points/query").mock(return_value=_points(*CHUNKS))
    respx.post(f"{RERANK}/rerank").mock(return_value=httpx.Response(503))
    with pytest.raises(RerankError, match="HTTP 503"):
        _retriever(cfg, reranker=_reranker()).retrieve(T, "Frist", 2)
