"""``build_query``: the filter sits in every prefetch and in the query; M8/M9 are detected (S2)."""

import pytest
from rd_support import CONFIGS, qdrant_point

from rag_demo.config import load_config
from rag_demo.errors import RetrievalError
from rag_demo.models import QueryVectors, SparseVector
from rag_demo.retrieval.bugs import build_shared_query
from rag_demo.retrieval.filters import SHARED, tenant_filter
from rag_demo.retrieval.query_builder import (
    Prefetch,
    QdrantQuery,
    SparseQuery,
    build_query,
    to_hits,
)
from rag_demo.retrieval.testing import assert_tenant_scoped

GOOD = load_config(CONFIGS / "rag.yaml")
POST = load_config(CONFIGS / "bugs" / "tenant_filter_post_topk.yaml")
UNFILTERED = load_config(CONFIGS / "bugs" / "shared_public_unfiltered.yaml")
DENSE_ONLY = GOOD.model_copy(
    update={"retrieval": GOOD.retrieval.model_copy(update={"hybrid": False})}
)
VECS = QueryVectors(dense=[0.1, 0.2, 0.3], sparse=SparseVector(indices=[1, 5], values=[1.0, 1.0]))
T = "kanzlei_mueller"


def test_hybrid_has_two_prefetches_and_each_carries_the_filter() -> None:
    request = build_query(T, VECS, GOOD)
    assert [p.using for p in request.prefetch] == ["dense", "sparse"]
    assert all(p.filter == tenant_filter(T) for p in request.prefetch)
    assert request.filter == tenant_filter(T)  # defence in depth: the fused query too
    assert request.query.rrf.k == 60
    assert request.limit == GOOD.top_k


def test_the_wire_body_has_rrf_k_the_prefetch_limit_and_the_filter_everywhere() -> None:
    body = build_query(T, VECS, GOOD, limit=10).to_json()
    flt = {"must": [{"key": "tenant_id", "match": {"any": [T, SHARED]}}]}
    assert body["query"] == {"rrf": {"k": 60}}
    assert body["limit"] == 10
    assert body["with_payload"] is True
    assert body["filter"] == flt
    prefetch = body["prefetch"]
    assert isinstance(prefetch, list)
    assert [p["filter"] for p in prefetch] == [flt, flt]
    assert [p["limit"] for p in prefetch] == [50, 50]
    assert prefetch[1]["query"] == {"indices": [1, 5], "values": [1.0, 1.0]}
    assert prefetch[0]["query"] == [0.1, 0.2, 0.3]


def test_dense_only_has_one_filtered_prefetch() -> None:
    request = build_query(T, VECS, DENSE_ONLY)
    assert [p.using for p in request.prefetch] == ["dense"]
    assert request.prefetch[0].filter == tenant_filter(T)
    assert_tenant_scoped(request, T)


def test_shared_public_asks_only_for_itself() -> None:
    request = build_query(SHARED, VECS, GOOD)
    assert request.filter is not None
    assert request.filter.must[0].match.any == (SHARED,)


def test_an_unknown_tenant_is_refused_before_any_request_exists() -> None:
    with pytest.raises(ValueError, match="unknown tenant"):
        build_query("Kanzlei Müller", VECS, GOOD)


def test_the_correct_request_is_tenant_scoped_also_as_wire_json() -> None:
    request = build_query(T, VECS, GOOD)
    assert_tenant_scoped(request, T)
    assert_tenant_scoped(request.to_json(), T)


def test_assert_tenant_scoped_rejects_the_request_of_another_tenant() -> None:
    with pytest.raises(AssertionError, match="not tenant-scoped"):
        assert_tenant_scoped(build_query("versicherung_nord", VECS, GOOD), T)


def test_m8_detector_a_request_without_prefetch_filters_fails() -> None:
    request = build_query(T, VECS, GOOD)
    no_filters = request.model_copy(
        update={"prefetch": tuple(p.model_copy(update={"filter": None}) for p in request.prefetch)}
    )
    with pytest.raises(AssertionError, match=r"prefetch\[0\]"):
        assert_tenant_scoped(no_filters, T)


def test_m8_detector_one_unfiltered_prefetch_fails() -> None:
    request = build_query(T, VECS, GOOD)
    first, second = request.prefetch
    half = request.model_copy(
        update={"prefetch": (first, second.model_copy(update={"filter": None}))}
    )
    with pytest.raises(AssertionError, match=r"prefetch\[1\]"):
        assert_tenant_scoped(half, T)


def test_m8_detector_a_missing_top_level_filter_fails() -> None:
    request = build_query(T, VECS, GOOD).model_copy(update={"filter": None})
    with pytest.raises(AssertionError, match="top-level"):
        assert_tenant_scoped(request, T)


def test_the_post_topk_bug_request_has_no_filter_anywhere_and_is_detected() -> None:
    request = build_query(T, VECS, POST)
    assert request.filter is None
    assert all(p.filter is None for p in request.prefetch)
    with pytest.raises(AssertionError):
        assert_tenant_scoped(request, T)


def test_m9_detector_an_extra_unfiltered_shared_public_prefetch_fails() -> None:
    request = build_query(T, VECS, GOOD)
    extra = Prefetch(query=[0.1, 0.2, 0.3], using="dense", limit=50)
    leaky = request.model_copy(update={"prefetch": (*request.prefetch, extra)})
    with pytest.raises(AssertionError, match=r"prefetch\[2\]"):
        assert_tenant_scoped(leaky, T)


def test_m9_detector_a_should_filter_is_not_accepted() -> None:
    flt = {"should": [{"key": "tenant_id", "match": {"any": [T, SHARED]}}]}
    leg = {"query": [0.1, 0.2, 0.3], "using": "dense", "limit": 50, "filter": flt}
    body = {"prefetch": [leg], "query": {"rrf": {"k": 60}}, "filter": flt, "limit": 4}
    with pytest.raises(AssertionError, match="recognised"):
        assert_tenant_scoped(body, T)


def test_m9_detector_a_prefetch_that_matches_shared_public_only_fails() -> None:
    request = build_query(T, VECS, GOOD)
    shared_only = request.prefetch[0].model_copy(update={"filter": tenant_filter(SHARED)})
    leaky = request.model_copy(update={"prefetch": (shared_only, request.prefetch[1])})
    with pytest.raises(AssertionError, match=r"prefetch\[0\]"):
        assert_tenant_scoped(leaky, T)


def test_a_request_without_legs_is_not_scoped() -> None:
    empty = build_query(T, VECS, GOOD).model_copy(update={"prefetch": ()})
    with pytest.raises(AssertionError, match="no prefetch"):
        assert_tenant_scoped(empty, T)


def test_the_unfiltered_merge_bug_sends_a_second_query_without_any_filter() -> None:
    assert build_shared_query(VECS, GOOD, 4) is None
    second = build_shared_query(VECS, UNFILTERED, 4)
    assert isinstance(second, QdrantQuery)
    assert second.filter is None
    assert all(p.filter is None for p in second.prefetch)
    with pytest.raises(AssertionError):
        assert_tenant_scoped(second, T)


def test_sparse_query_is_part_of_the_wire_body() -> None:
    assert SparseQuery(indices=[1], values=[1.0]).model_dump() == {"indices": [1], "values": [1.0]}


def test_to_hits_maps_payload_and_ranks_from_one() -> None:
    hits = to_hits([qdrant_point("gii-bgb-622#1", 0.3), qdrant_point("gii-bgb-620#0", 0.2)])
    assert [(h.rank, h.chunk_id, h.tenant_id) for h in hits] == [
        (1, "gii-bgb-622#1", "shared_public"),
        (2, "gii-bgb-620#0", "shared_public"),
    ]
    assert hits[0].citation_key == "§ 622 BGB"
    assert hits[0].lang == "de"
    assert hits[0].score == 0.3


@pytest.mark.parametrize("bad", [[{"score": 1.0}], [{"payload": {}}], ["x"], [None]])
def test_to_hits_refuses_an_unexpected_point_shape(bad: list[object]) -> None:
    with pytest.raises(RetrievalError, match="unexpected point shape"):
        to_hits(bad)
