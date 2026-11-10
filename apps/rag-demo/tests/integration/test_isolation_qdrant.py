"""Tenant isolation at the Qdrant level (T3.7): ``QdrantRetriever`` directly, every probe.

Real Qdrant (Testcontainers) with the fixture corpus and its canaries, real TEI CPU embeddings.
The post-condition guard is off, so what is proven is the filter inside every built query; every
request body sent to Qdrant is also checked with ``assert_tenant_scoped``. The M8 simulation
patches the filters out of the built query and shows that this suite then fails.
"""

import json
from collections.abc import Callable

import httpx
import pytest
from rd_support import CONFIGS, FIXTURE_CORPUS, build_test_retriever
from support.canaries import load_registry
from support.probes import Probe, Seen, build_probes, summary, violations

import rag_demo.retrieval.retriever as retriever_module
from rag_demo.config import load_config
from rag_demo.models import RagConfig
from rag_demo.retrieval.query_builder import QdrantQuery, build_query
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.retrieval.testing import assert_tenant_scoped

pytestmark = pytest.mark.integration
CFG = load_config(CONFIGS / "rag.yaml")
REGISTRY = load_registry(FIXTURE_CORPUS / "canaries.json")
PROBES = build_probes(REGISTRY)
TOP_K = 8  # twice the app's top_k: a deeper cut gives a leak more room to show


class Recorder(httpx.HTTPTransport):
    """Real transport that keeps every Query API body sent to Qdrant."""

    def __init__(self) -> None:
        super().__init__()
        self.bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/points/query"):
            self.bodies.append(json.loads(request.content))
        return super().handle_request(request)


def _retriever(qdrant: str, tei: str, cfg: RagConfig = CFG) -> tuple[QdrantRetriever, Recorder]:
    recorder = Recorder()
    client = httpx.Client(transport=recorder, timeout=30)
    return build_test_retriever(cfg, qdrant, tei, guard=False, client=client), recorder


def check_probes(retriever: QdrantRetriever, recorder: Recorder, probes: list[Probe]) -> int:
    """Run every probe; return the number of probes; raise ``AssertionError`` on any leak."""
    failures: list[str] = []
    for probe in probes:
        start = len(recorder.bodies)
        hits = retriever.retrieve(probe.asker, probe.question, TOP_K)
        for body in recorder.bodies[start:]:
            assert_tenant_scoped(body, probe.asker)
        seen = Seen(answer="", chunks=tuple((h.tenant_id, h.text) for h in hits))
        failures += [f"{probe.probe_id}: {v}" for v in violations(probe.asker, seen, REGISTRY)]
    assert not failures, "\n".join(failures)
    return len(probes)


def _unfiltered(build: Callable[..., QdrantQuery]) -> Callable[..., QdrantQuery]:
    """``build_query`` with the tenant filters patched out (the M8 shape: no filter anywhere)."""

    def build_without_filter(*args: object, **kwargs: object) -> QdrantQuery:
        query = build(*args, **kwargs)
        legs = tuple(leg.model_copy(update={"filter": None}) for leg in query.prefetch)
        return query.model_copy(update={"prefetch": legs, "filter": None})

    return build_without_filter


def test_every_probe_retrieves_only_allowed_tenants_and_every_query_is_scoped(
    fixture_qdrant_url: str, tei_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    retriever, recorder = _retriever(fixture_qdrant_url, tei_url)
    count = check_probes(retriever, recorder, PROBES)
    assert count >= 54
    assert len(recorder.bodies) == count  # one scoped Query API request per probe
    with capsys.disabled():
        print(f"\nqdrant-level isolation: {summary(count, 0)}")  # noqa: T201  # Done-when evidence


def test_the_owning_tenant_retrieves_each_canary_document(
    fixture_qdrant_url: str, tei_url: str
) -> None:
    retriever, _ = _retriever(fixture_qdrant_url, tei_url)
    controls = {p.canary.doc_id: p for p in PROBES if p.kind in {"semantic", "token"}}
    assert len(controls) == len(REGISTRY.canaries)
    missed = [
        doc_id
        for doc_id, p in controls.items()
        if doc_id not in {h.doc_id for h in retriever.retrieve(p.owner, p.question, CFG.top_k)}
    ]
    assert not missed, missed


def test_with_the_prefetch_filters_patched_out_the_suite_fails(
    fixture_qdrant_url: str, tei_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8 simulation: without filters both the scope check and the hit check catch it."""
    monkeypatch.setattr(retriever_module, "build_query", _unfiltered(build_query))
    retriever, recorder = _retriever(fixture_qdrant_url, tei_url)
    with pytest.raises(AssertionError, match="not tenant-scoped"):
        check_probes(retriever, recorder, PROBES)
    # the hit check alone fails too: foreign chunks come back once the filter is gone
    leaked = 0
    for probe in PROBES:
        hits = retriever.retrieve(probe.asker, probe.question, TOP_K)
        seen = Seen(answer="", chunks=tuple((h.tenant_id, h.text) for h in hits))
        leaked += bool(violations(probe.asker, seen, REGISTRY))
    assert leaked > 0
