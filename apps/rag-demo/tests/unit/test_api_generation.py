"""``POST /v1/query`` with the generation package wired in (respx on the real Qdrant/TEI shapes)."""

import json
import logging
import re

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from rd_support import CONFIGS, qdrant_point

from rag_demo.api import create_app
from rag_demo.config import Settings, load_config
from rag_demo.wiring import expected_fingerprint

QDRANT = "http://qdrant.test:6333/collections/chunks_active"
SETTINGS = Settings(
    qdrant_url="http://qdrant.test:6333", llm_url="http://llm:8080", embed_url="http://embed:8090"
)
CFG = load_config(CONFIGS / "rag.yaml")
CHUNKS = ["gii-bgb-622#1", "gii-kschg-1#0", "gii-bgb-620#0", "gii-bgb-621#0"]
LLM = "http://llm:8080/v1/chat/completions"


def _mock(points: list[str], llm: httpx.Response | Exception) -> respx.Route:
    meta = {
        "corpus_version": "fixture-1",
        "tenants": ["kanzlei_mueller", "shared_public"],
        "analyzer": expected_fingerprint(CFG),
        "complete": True,
    }
    respx.get(QDRANT).mock(
        return_value=httpx.Response(200, json={"result": {"config": {"metadata": meta}}})
    )
    respx.post("http://embed:8090/embed").mock(
        return_value=httpx.Response(200, json=[[0.01] * CFG.embed.dim])
    )
    found = [qdrant_point(cid, 0.3 - i * 0.01) for i, cid in enumerate(points)]
    respx.post(f"{QDRANT}/points/query").mock(
        return_value=httpx.Response(200, json={"result": {"points": found}})
    )
    if isinstance(llm, httpx.Response):
        return respx.post(LLM).mock(return_value=llm)
    return respx.post(LLM).mock(side_effect=llm)


def _query() -> dict[str, object]:
    return {"tenant_id": "kanzlei_mueller", "question": "Welche Frist gilt?", "request_id": "r-42"}


@respx.mock
def test_empty_retrieval_is_refused_with_no_generator_call() -> None:
    llm = _mock([], httpx.Response(200, json={}))
    body = TestClient(create_app(CFG, settings=SETTINGS)).post("/v1/query", json=_query()).json()
    assert body["refused"] is True
    assert body["answer"].startswith("Die Dokumente enthalten dazu keine Information")
    assert body["chunks"] == []
    assert llm.call_count == 0


@respx.mock
def test_a_generator_timeout_is_a_503_without_stack_trace_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_CANDIDATE_API_KEY", "k1-secret-value")
    _mock(CHUNKS, httpx.ReadTimeout("slow"))
    resp = TestClient(create_app(CFG, settings=SETTINGS)).post("/v1/query", json=_query())
    assert resp.status_code == 503
    assert resp.json() == {"detail": "backend unavailable"}
    assert "k1-secret-value" not in resp.text
    assert "Traceback" not in resp.text


@respx.mock
def test_the_prompt_chunk_ids_are_logged_at_debug_level_per_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reply = {
        "choices": [{"message": {"content": "Vier Wochen (§ 622 BGB)."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    _mock(CHUNKS, httpx.Response(200, json=reply))
    with caplog.at_level(logging.DEBUG, logger="rag_demo.api"):
        body = (
            TestClient(create_app(CFG, settings=SETTINGS)).post("/v1/query", json=_query()).json()
        )
    line = next(r.getMessage() for r in caplog.records if "prompt_chunk_ids" in r.getMessage())
    assert "request_id=r-42" in line
    prompted = [c["chunk_id"] for c in body["chunks"] if c["used_in_prompt"]]
    assert all(cid in line for cid in prompted)
    assert prompted == CHUNKS
    assert body["citations"] == ["§ 622 BGB"]


@respx.mock
def test_used_in_prompt_chunks_are_exactly_the_chunks_of_the_prompt_the_generator_sent() -> None:
    reply = {
        "choices": [{"message": {"content": "Vier Wochen (§ 622 BGB)."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    llm = _mock(CHUNKS, httpx.Response(200, json=reply))
    body = TestClient(create_app(CFG, settings=SETTINGS)).post("/v1/query", json=_query()).json()
    sent = json.loads(llm.calls.last.request.content)["messages"][1]["content"]
    in_prompt = re.findall(r'<dokument id="([^"]+)"', sent)
    assert in_prompt == [c["chunk_id"] for c in body["chunks"] if c["used_in_prompt"]]
    assert in_prompt == CHUNKS
