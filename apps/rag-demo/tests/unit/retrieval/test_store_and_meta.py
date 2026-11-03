"""``QdrantStore`` and ``CorpusMeta`` against Qdrant's REST API (respx records the calls)."""

import httpx
import pytest
import respx
from rd_support import CONFIGS, qdrant_point

from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.errors import IndexMismatchError, IndexUnavailableError, RetrievalError
from rag_demo.models import QueryVectors, SparseVector
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.query_builder import build_query
from rag_demo.retrieval.store import QdrantStore
from rag_demo.wiring import build_analyzer, expected_fingerprint

BASE = "http://qdrant.test:6333"
URL = f"{BASE}/collections/chunks_active"
CFG = load_config(CONFIGS / "rag.yaml")
EXPECTED = expected_fingerprint(CFG)
VECS = QueryVectors(dense=[0.1], sparse=SparseVector(indices=[1], values=[1.0]))
META = {
    "corpus_version": "fixture-1",
    "tenants": ["kanzlei_mueller", "shared_public"],
    "analyzer": EXPECTED,
    "complete": True,
}


def _info(meta: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"result": {"config": {"metadata": meta}}})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@respx.mock
def test_the_query_goes_to_the_collection_with_the_api_key_header() -> None:
    route = respx.post(f"{URL}/points/query").mock(
        return_value=httpx.Response(
            200, json={"result": {"points": [qdrant_point("gii-bgb-622#1", 0.3)]}}
        )
    )
    store = QdrantStore(BASE, "chunks_active", api_key="secret-key")
    points = store.query(build_query("kanzlei_mueller", VECS, CFG))
    assert len(points) == 1
    assert route.calls.last.request.headers["api-key"] == "secret-key"


@respx.mock
def test_no_api_key_header_when_the_key_is_unset_or_empty() -> None:
    route = respx.get(URL).mock(return_value=_info(META))
    for key in (None, ""):
        QdrantStore(BASE, "chunks_active", api_key=key).metadata()
        assert "api-key" not in route.calls.last.request.headers


@respx.mock
def test_an_error_names_the_status_but_never_the_key_or_the_body() -> None:
    respx.post(f"{URL}/points/query").mock(
        return_value=httpx.Response(403, text="forbidden secret-key")
    )
    with pytest.raises(RetrievalError, match="HTTP 403") as err:
        QdrantStore(BASE, "chunks_active", api_key="secret-key").query(
            build_query("kanzlei_mueller", VECS, CFG)
        )
    assert "secret-key" not in str(err.value)


@respx.mock
def test_an_unreachable_qdrant_is_a_retrieval_error() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("boom secret-key"))
    with pytest.raises(RetrievalError, match="unreachable") as err:
        QdrantStore(BASE, "chunks_active", api_key="secret-key").metadata()
    assert "secret-key" not in str(err.value)


@respx.mock
@pytest.mark.parametrize("body", [{}, {"result": {}}, {"result": {"points": "x"}}])
def test_an_unexpected_query_body_is_a_retrieval_error(body: dict[str, object]) -> None:
    respx.post(f"{URL}/points/query").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RetrievalError, match="unexpected body"):
        QdrantStore(BASE, "chunks_active").query(build_query("kanzlei_mueller", VECS, CFG))


@respx.mock
@pytest.mark.parametrize("body", [{}, {"result": {"config": {"metadata": 3}}}])
def test_a_collection_without_metadata_is_a_retrieval_error(body: dict[str, object]) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RetrievalError, match="no metadata"):
        QdrantStore(BASE, "chunks_active").metadata()


@respx.mock
def test_meta_is_cached_for_ten_seconds_then_re_read() -> None:
    route = respx.get(URL).mock(return_value=_info(META))
    clock = Clock()
    meta = CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED, clock=clock)
    assert meta.get()["corpus_version"] == "fixture-1"
    clock.now = 9.9
    meta.get()
    assert route.call_count == 1
    clock.now = 10.0
    meta.get()
    assert route.call_count == 2


@respx.mock
def test_meta_follows_an_alias_swap_within_the_ttl() -> None:
    route = respx.get(URL).mock(return_value=_info(META))
    clock = Clock()
    meta = CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED, clock=clock)
    assert meta.get()["corpus_version"] == "fixture-1"
    route.mock(return_value=_info({**META, "corpus_version": "fixture-2"}))
    clock.now = 11.0
    assert meta.get()["corpus_version"] == "fixture-2"


@respx.mock
def test_an_incomplete_index_is_refused() -> None:
    respx.get(URL).mock(return_value=_info({**META, "complete": False}))
    with pytest.raises(IndexUnavailableError, match="not complete; re-index"):
        CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED).get()


@respx.mock
def test_an_index_without_corpus_metadata_or_unreadable_is_unavailable() -> None:
    respx.get(URL).mock(return_value=_info({"complete": True}))
    with pytest.raises(IndexUnavailableError, match="index unavailable"):
        CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED).get()
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(IndexUnavailableError, match="index unavailable"):
        CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED).get()


@respx.mock
def test_an_index_built_with_another_analyzer_is_refused_never_served_dense_only() -> None:
    other = build_analyzer(
        CFG.model_copy(
            update={"analyzer": CFG.analyzer.model_copy(update={"compound_split": False})}
        )
    )
    stored = fingerprint(other, SparseEncoder())
    respx.get(URL).mock(return_value=_info({**META, "analyzer": stored}))
    with pytest.raises(IndexMismatchError, match="compound_split"):
        CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED).get()


@respx.mock
def test_an_index_without_a_fingerprint_is_refused() -> None:
    meta = {k: v for k, v in META.items() if k != "analyzer"}
    respx.get(URL).mock(return_value=_info(meta))
    with pytest.raises(IndexMismatchError, match="re-index"):
        CorpusMeta(QdrantStore(BASE, "chunks_active"), EXPECTED).get()


@respx.mock
def test_the_metadata_read_sends_the_api_key() -> None:
    route = respx.get(URL).mock(return_value=_info(META))
    CorpusMeta(QdrantStore(BASE, "chunks_active", api_key="k9"), EXPECTED).get()
    assert route.calls.last.request.headers["api-key"] == "k9"
