"""Tenant isolation of ``QdrantRetriever`` on the fixture corpus (own Qdrant with an API key).

Everything here runs with the post-condition guard **off**, so the filter inside the query is
what is proven, not the safety net. Real Qdrant (Testcontainers, ``QDRANT__SERVICE__API_KEY``)
and the real TEI CPU service.
"""

import re
from collections.abc import Iterator

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rd_support import (
    CONFIGS,
    FIXTURE_CORPUS,
    build_test_retriever,
    compose_image,
    fixture_rows,
    wait_http,
)
from testcontainers.core.container import DockerContainer

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.errors import IndexMismatchError, RetrievalError
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.indexer import Indexer, IndexTarget
from rag_demo.index.naming import ALIAS
from rag_demo.models import QueryVectors, RagConfig
from rag_demo.retrieval.filters import allowed_tenants
from rag_demo.retrieval.query_builder import build_query, to_hits
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.retrieval.store import QdrantStore
from rag_demo.wiring import build_analyzer

pytestmark = pytest.mark.integration
KEY = "integration-test-key"
CUSTOMERS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")
CANARY_QUERY = "Kündigungsfrist Rahmenvertrag Bergmann"
GOOD = load_config(CONFIGS / "rag.yaml")


@pytest.fixture(scope="module")
def qdrant_keyed(tei_url: str) -> Iterator[str]:
    """A Qdrant that requires an API key, with the fixture corpus indexed through that key."""
    container = (
        DockerContainer(compose_image("qdrant"))
        .with_env("QDRANT__SERVICE__API_KEY", KEY)
        .with_exposed_ports(6333)
    )
    with container:
        url = f"http://127.0.0.1:{container.get_exposed_port(6333)}"
        wait_http(f"{url}/readyz")
        Indexer(
            url,
            TeiDenseEncoder(GOOD.embed, tei_url),
            build_analyzer(GOOD),
            SparseEncoder(),
            target=IndexTarget(GOOD.embed.model),
            api_key=KEY,
        ).index(FIXTURE_CORPUS)
        yield url


def _retriever(
    qdrant_keyed: str, tei_url: str, cfg: RagConfig = GOOD, *, guard: bool = False
) -> QdrantRetriever:
    return build_test_retriever(cfg, qdrant_keyed, tei_url, api_key=KEY, guard=guard)


@pytest.fixture(scope="module")
def retriever(qdrant_keyed: str, tei_url: str) -> QdrantRetriever:
    return _retriever(qdrant_keyed, tei_url)


def test_the_foreign_canary_does_not_come_back_for_another_tenant(retriever) -> None:  # type: ignore[no-untyped-def]  # fixture
    hits = retriever.retrieve("kanzlei_mueller", CANARY_QUERY, 8)
    assert hits
    assert all(h.tenant_id != "versicherung_nord" for h in hits)
    assert not any("CANARY-VN-" in h.text for h in hits)


def test_without_the_filter_the_foreign_canary_ranks_first(qdrant_keyed: str, tei_url: str) -> None:
    """The M8 contrast: the query is a perfect match for the canary chunk of another tenant."""
    own = _retriever(qdrant_keyed, tei_url).retrieve("versicherung_nord", CANARY_QUERY, 4)
    assert own[0].chunk_id == "syn-vn-rahmenvertrag-bergmann#0"
    # the same question without the filter (the request the M8 bug sends): the canary is first
    bug = load_config(CONFIGS / "bugs" / "tenant_filter_post_topk.yaml")
    vectors = QueryVectors(
        dense=TeiDenseEncoder(bug.embed, tei_url).encode([CANARY_QUERY])[0].tolist(),
        sparse=SparseEncoder().encode_query(build_analyzer(bug).tokens(CANARY_QUERY)),
    )
    unfiltered = QdrantStore(qdrant_keyed, ALIAS, api_key=KEY).query(
        build_query("kanzlei_mueller", vectors, bug, limit=4)
    )
    assert to_hits(unfiltered)[0].tenant_id == "versicherung_nord"
    # ... and the bug returns it to the wrong tenant (backfilled after the cut)
    leaked = _retriever(qdrant_keyed, tei_url, bug).retrieve("kanzlei_mueller", CANARY_QUERY, 4)
    assert any(h.chunk_id == "syn-vn-rahmenvertrag-bergmann#0" for h in leaked)


@pytest.mark.parametrize("tenant", CUSTOMERS)
def test_shared_public_is_retrievable_by_every_customer_tenant(retriever, tenant: str) -> None:  # type: ignore[no-untyped-def]  # fixture
    hits = retriever.retrieve(tenant, "Kündigungsfrist nach § 622 BGB im Arbeitsverhältnis", 8)
    assert any(h.chunk_id.startswith("gii-bgb-622#") for h in hits)
    assert {h.tenant_id for h in hits} <= allowed_tenants(tenant)


@pytest.mark.parametrize("top_k", [1, 3, 8])
def test_top_k_is_respected_and_ranks_are_contiguous(retriever, top_k: int) -> None:  # type: ignore[no-untyped-def]  # fixture
    hits = retriever.retrieve("kanzlei_mueller", "Kündigungsfrist", top_k)
    assert 1 <= len(hits) <= top_k
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


def test_rrf_k_60_reaches_qdrant(retriever) -> None:  # type: ignore[no-untyped-def]  # fixture
    """With RRF k=60 the best possible fused score is 2/60 (first in both legs; Qdrant ranks
    from 0); Qdrant's own default k of 2 would give about 1."""
    top = retriever.retrieve("kanzlei_mueller", "Kündigungsfrist nach zwei Jahren", 3)[0]
    assert 0 < top.score <= 2 / 60 + 1e-6


def test_a_query_of_stop_words_only_still_gets_an_answer(retriever) -> None:  # type: ignore[no-untyped-def]  # fixture
    assert retriever.retrieve("kanzlei_mueller", "und der die das", 3)


_SENTENCES = [
    s.strip()
    for row in fixture_rows().values()
    for s in re.split(r"(?<=[.;:])\s+", str(row["text"]))
    if 20 < len(s.strip()) < 200
]


@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(tenant=st.sampled_from((*CUSTOMERS, "shared_public")), query=st.sampled_from(_SENTENCES))
def test_hits_always_belong_to_allowed_tenants(retriever, tenant: str, query: str) -> None:  # type: ignore[no-untyped-def]  # fixture
    hits = retriever.retrieve(tenant, query, 8)
    assert {h.tenant_id for h in hits} <= allowed_tenants(tenant)


def test_the_api_key_is_required_and_sent(qdrant_keyed: str, tei_url: str) -> None:
    """The follow-up of T3.4: the retriever and the metadata check send ``QDRANT_API_KEY``."""
    assert httpx.get(f"{qdrant_keyed}/collections", timeout=10).status_code == 401
    with pytest.raises(RetrievalError):  # no key: the metadata read is refused, never served
        build_test_retriever(GOOD, qdrant_keyed, tei_url).retrieve("kanzlei_mueller", "Frist", 3)
    assert _retriever(qdrant_keyed, tei_url).retrieve("kanzlei_mueller", "Frist", 3)


def test_a_retriever_with_another_analyzer_is_refused_on_the_real_index(
    qdrant_keyed: str, tei_url: str
) -> None:
    other = GOOD.model_copy(
        update={"analyzer": GOOD.analyzer.model_copy(update={"compound_split": False})}
    )
    with pytest.raises(IndexMismatchError, match="compound_split"):
        _retriever(qdrant_keyed, tei_url, other).retrieve("kanzlei_mueller", "Frist", 3)
