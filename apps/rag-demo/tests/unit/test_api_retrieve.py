"""``POST /v1/retrieve`` (D218): chunks only, no generator, the same retrieval as ``/v1/query``."""

import json
from typing import Any

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from rd_support import CONFIGS, REPO, qdrant_point

from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.api import create_app
from rag_demo.config import Settings, config_hash, load_config
from rag_demo.generate import OpenAICompatGenerator
from rag_demo.models import RagConfig
from rag_demo.wiring import build_analyzer, expected_fingerprint

QDRANT = "http://qdrant.test:6333/collections/chunks_active"
RERANK = "http://rerank-cpu:8201"
SETTINGS = Settings(
    qdrant_url="http://qdrant.test:6333", llm_url="http://llm:8080", embed_url="http://embed:8090"
)
CHUNKS = ["gii-bgb-622#1", "gii-kschg-1#0", "gii-bgb-620#0", "gii-bgb-621#0"]
OPENAPI = yaml.safe_load((REPO / "schemas" / "target-api-v1.openapi.yaml").read_text("utf-8"))
CHUNK_KEYS = {"chunk_id", "doc_id", "tenant_id", "text", "score", "rank"}


def _cfg(*, rerank: bool = False, on_retrieve: bool = True) -> RagConfig:
    cfg = load_config(CONFIGS / "rag.yaml")
    if not rerank:
        return cfg
    return cfg.model_copy(
        update={
            "reranker": "on",
            "rerank": cfg.rerank.model_copy(update={"top_n": 4, "on_retrieve": on_retrieve}),
        }
    )


def _request(tenant: str = "kanzlei_mueller", **extra: object) -> dict[str, object]:
    return {"tenant_id": tenant, "question": "Welche Frist gilt?", "request_id": "r1", **extra}


def _mock_stack(cfg: RagConfig, *ids: str) -> dict[str, respx.Route]:
    meta = {
        "corpus_version": "fixture-1",
        "tenants": ["kanzlei_mueller", "shared_public", "versicherung_nord"],
        "analyzer": expected_fingerprint(cfg),
        "complete": True,
    }
    points = [qdrant_point(cid, 0.3 - i * 0.01) for i, cid in enumerate(ids or CHUNKS)]
    return {
        "meta": respx.get(QDRANT).mock(
            return_value=httpx.Response(200, json={"result": {"config": {"metadata": meta}}})
        ),
        "embed": respx.post("http://embed:8090/embed").mock(
            return_value=httpx.Response(200, json=[[0.01] * cfg.embed.dim])
        ),
        "query": respx.post(f"{QDRANT}/points/query").mock(
            return_value=httpx.Response(200, json={"result": {"points": points}})
        ),
        "llm": respx.post("http://llm:8080/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Vier Wochen (§ 622 BGB)."}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        ),
    }


def _client(cfg: RagConfig, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RERANK_URL", RERANK)
    return TestClient(create_app(cfg, settings=SETTINGS))


def _rerank_route(order: list[int]) -> respx.Route:
    scores = [{"index": i, "score": 1.0 - n * 0.1} for n, i in enumerate(order)]
    return respx.post(f"{RERANK}/rerank").mock(return_value=httpx.Response(200, json=scores))


@respx.mock
def test_retrieve_answers_with_chunks_only_and_never_touches_the_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the generator must not be called on /v1/retrieve")  # noqa: EM101

    monkeypatch.setattr(OpenAICompatGenerator, "answer", refuse)
    routes = _mock_stack(_cfg())
    client = _client(_cfg(), monkeypatch)
    resp = client.post("/v1/retrieve", json=_request(top_k=3))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"chunks"}
    assert [c["rank"] for c in body["chunks"]] == [1, 2, 3]
    assert all(set(c) == CHUNK_KEYS for c in body["chunks"])  # used_in_prompt is absent
    assert routes["llm"].call_count == 0


@respx.mock
def test_retrieve_has_the_chunks_and_order_of_query_when_on_retrieve_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(rerank=True)
    _mock_stack(cfg)
    _rerank_route([3, 2, 1, 0])
    client = _client(cfg, monkeypatch)
    retrieved = client.post("/v1/retrieve", json=_request()).json()["chunks"]
    queried = client.post("/v1/query", json=_request()).json()["chunks"]
    assert [c["chunk_id"] for c in retrieved] == list(reversed(CHUNKS))
    assert retrieved == [{k: v for k, v in c.items() if k != "used_in_prompt"} for c in queried]


@respx.mock
def test_on_retrieve_false_skips_the_reranker_on_retrieve_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(rerank=True, on_retrieve=False)
    _mock_stack(cfg)
    rerank = _rerank_route([3, 2, 1, 0])
    client = _client(cfg, monkeypatch)
    retrieved = client.post("/v1/retrieve", json=_request()).json()["chunks"]
    assert rerank.call_count == 0
    assert [c["chunk_id"] for c in retrieved] == CHUNKS  # the fused order, cut to top_k
    queried = client.post("/v1/query", json=_request()).json()["chunks"]
    assert rerank.call_count == 1
    assert [c["chunk_id"] for c in queried] == list(reversed(CHUNKS))


def test_on_retrieve_is_part_of_the_config_hash_and_defaults_to_true() -> None:
    on = _cfg(rerank=True)
    off = _cfg(rerank=True, on_retrieve=False)
    assert on.rerank.on_retrieve is True
    assert config_hash(on) != config_hash(off)


@respx.mock
def test_an_unknown_tenant_is_422_like_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_stack(_cfg())
    client = _client(_cfg(), monkeypatch)
    for path in ("/v1/retrieve", "/v1/query"):
        resp = client.post(path, json=_request(tenant="gibt_es_nicht"))
        assert resp.status_code == 422
        assert "unknown tenant" in resp.text


def test_validation_is_the_one_of_query(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(_cfg(), monkeypatch)
    assert client.post("/v1/retrieve", json=_request(top_k=0)).status_code == 422
    assert client.post("/v1/retrieve", json=_request(top_k=51)).status_code == 422
    assert client.post("/v1/retrieve", json={**_request(), "extra": 1}).status_code == 422
    assert client.post("/v1/retrieve", json={**_request(), "question": ""}).status_code == 422


@respx.mock
def test_a_foreign_chunk_is_never_returned_with_the_guard_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_stack(_cfg(), "syn-vn-rahmenvertrag-bergmann#0", "gii-bgb-622#1")
    client = _client(_cfg(), monkeypatch)
    resp = client.post("/v1/retrieve", json=_request())
    assert resp.status_code == 503
    assert "Bergmann" not in resp.text
    assert "versicherung_nord" not in resp.text


@respx.mock
def test_requests_are_counted_in_health(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_stack(_cfg())
    client = _client(_cfg(), monkeypatch)
    before = client.get("/v1/health").json()["stats"]["requests"]
    client.post("/v1/retrieve", json=_request())
    client.post("/v1/retrieve", json=_request())
    assert client.get("/v1/health").json()["stats"]["requests"] == before + 2


@respx.mock
def test_a_failing_reranker_is_503_without_details(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(rerank=True)
    _mock_stack(cfg)
    respx.post(f"{RERANK}/rerank").mock(return_value=httpx.Response(500, text="traceback..."))
    resp = _client(cfg, monkeypatch).post("/v1/retrieve", json=_request())
    assert resp.status_code == 503
    assert "traceback" not in resp.text


@respx.mock
def test_an_index_with_another_analyzer_is_503_and_names_the_re_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg()
    routes = _mock_stack(cfg)
    other = cfg.model_copy(
        update={"analyzer": cfg.analyzer.model_copy(update={"compound_split": False})}
    )
    meta = {
        "corpus_version": "x",
        "tenants": ["kanzlei_mueller"],
        "analyzer": fingerprint(build_analyzer(other), SparseEncoder()),
        "complete": True,
    }
    routes["meta"].mock(
        return_value=httpx.Response(200, json={"result": {"config": {"metadata": meta}}})
    )
    resp = _client(cfg, monkeypatch).post("/v1/retrieve", json=_request())
    assert resp.status_code == 503
    assert "re-index" in resp.text
    assert routes["query"].call_count == 0


@respx.mock
def test_the_response_validates_against_the_checked_in_openapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_stack(_cfg())
    body: Any = _client(_cfg(), monkeypatch).post("/v1/retrieve", json=_request()).json()
    schema = {"$ref": "#/components/schemas/RetrieveResponse", "components": OPENAPI["components"]}
    Draft202012Validator(schema).validate(json.loads(json.dumps(body)))
