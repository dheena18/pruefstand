"""T8.4: request validation, error bodies, CORS and logging of the public app."""

import re
from pathlib import Path

import httpx
import pytest
import respx
from pub_support import (
    CFG,
    DASHBOARD_DEFAULT_TIMEOUT_S,
    assert_public_error,
    client_for,
    mock_backend,
    query_body,
)

from rag_demo.retrieval.retriever import QdrantRetriever


def test_the_public_profile_loads_with_the_reranker_off_and_a_server_timeout_below_the_client() -> (
    None
):
    assert CFG.public_mode is True
    assert CFG.reranker == "off"
    assert CFG.public is not None
    assert CFG.public.timeout_s < DASHBOARD_DEFAULT_TIMEOUT_S
    assert CFG.public.rate_per_min == 10
    assert CFG.public.daily_per_key == 100


@respx.mock
def test_a_valid_query_is_answered_with_a_server_made_request_id(tmp_path: Path) -> None:
    llm = mock_backend()
    resp = client_for(tmp_path).post(
        "/v1/query", json=query_body(request_id="client-chosen", top_k=50)
    )
    assert resp.status_code == 200
    assert resp.json()["answer"].startswith("Vier Wochen")
    assert llm.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        query_body(tenant_id="evil_corp"),
        query_body(question="x" * 501),
        query_body(question=""),
        {"tenant_id": "kanzlei_mueller"},
        {**query_body(), "extra": 1},
    ],
)
def test_an_invalid_body_is_422_invalid_request_without_any_backend_call(
    tmp_path: Path, body: dict[str, object]
) -> None:
    llm = mock_backend()
    resp = client_for(tmp_path).post("/v1/query", json=body)
    assert_public_error(resp, 422, "invalid_request")
    assert llm.call_count == 0


@respx.mock
def test_a_body_over_8_kb_is_413_body_too_large(tmp_path: Path) -> None:
    mock_backend()
    resp = client_for(tmp_path).post("/v1/query", json=query_body(question="x" * 9000))
    assert_public_error(resp, 413, "body_too_large")


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        {"tenant_id": ["kanzlei_mueller"], "question": "Frage?"},
        {"tenant_id": {"a": 1}, "question": "Frage?"},
        {"tenant_id": None, "question": "Frage?"},
        {"tenant_id": 7, "question": "Frage?"},
        {"tenant_id": "kanzlei_mueller", "question": ["Frage?"]},
        {"tenant_id": "kanzlei_mueller", "question": 5},
        {"tenant_id": "kanzlei_mueller", "question": "Frage?", "top_k": "viele"},
        {"tenant_id": "kanzlei_mueller", "question": "Frage?", "top_k": [1]},
        {"tenant_id": "kanzlei_mueller", "question": "Frage?", "request_id": {"x": 1}},
        [1, 2],
        "text",
        None,
    ],
)
def test_malformed_field_types_are_public_422_with_cors_never_a_500(
    tmp_path: Path, body: object
) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_allowed_origin="http://localhost:4175")
    resp = client.post("/v1/query", json=body, headers={"Origin": "http://localhost:4175"})
    assert_public_error(resp, 422, "invalid_request")
    assert resp.headers["access-control-allow-origin"] == "http://localhost:4175"


@respx.mock
def test_invalid_json_and_an_unexpected_crash_are_public_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_allowed_origin="http://localhost:4175")
    garbage = client.post(
        "/v1/query", content=b"{not json", headers={"Origin": "http://localhost:4175"}
    )
    assert_public_error(garbage, 422, "invalid_request")
    monkeypatch.setattr(
        "rag_demo.public.middleware.checked_body",
        lambda *_: (_ for _ in ()).throw(RuntimeError("x")),
    )
    crashed = client.post(
        "/v1/query", json=query_body(), headers={"Origin": "http://localhost:4175"}
    )
    assert_public_error(crashed, 503, "server_error")
    assert crashed.headers["access-control-allow-origin"] == "http://localhost:4175"


@respx.mock
def test_the_server_makes_the_request_id_and_the_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mock_backend()
    seen: list[int] = []
    original = QdrantRetriever.retrieve

    def spy(self: QdrantRetriever, tenant: str, question: str, top_k: int) -> object:
        seen.append(top_k)
        return original(self, tenant, question, top_k)

    monkeypatch.setattr(QdrantRetriever, "retrieve", spy)
    caplog.set_level("DEBUG")
    resp = client_for(tmp_path).post(
        "/v1/query", json=query_body(request_id="client-chosen-id", top_k=50)
    )
    assert resp.status_code == 200
    assert seen == [CFG.top_k]  # the client's top_k 50 is ignored
    assert "client-chosen-id" not in caplog.text
    assert re.search(r"request_id=[0-9a-f]{32} ", caplog.text)  # the server's own id


@respx.mock
def test_the_question_never_reaches_a_log(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    mock_backend()
    caplog.set_level("DEBUG")
    marker = "Streng geheime Frage 4711"
    client_for(tmp_path).post("/v1/query", json=query_body(question=marker))
    client_for(tmp_path).post("/v1/query", json=query_body(question=marker, tenant_id="nope"))
    assert marker not in caplog.text


@respx.mock
def test_cors_only_for_the_dashboard_origin(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_allowed_origin="http://localhost:4175")
    good = client.post("/v1/query", json=query_body(), headers={"Origin": "http://localhost:4175"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:4175"
    bad = client.post("/v1/query", json=query_body(), headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    refused = client_for(tmp_path, demo_rate_per_min=1, demo_allowed_origin="http://localhost:4175")
    refused.post("/v1/query", json=query_body())
    limited = refused.post(
        "/v1/query", json=query_body(), headers={"Origin": "http://localhost:4175"}
    )
    assert limited.status_code == 429
    assert limited.headers["access-control-allow-origin"] == "http://localhost:4175"
    assert "retry-after" in limited.headers["access-control-expose-headers"].lower()


@respx.mock
def test_a_backend_failure_is_a_public_error_body_not_a_stack_trace(tmp_path: Path) -> None:
    mock_backend(httpx.Response(500, text="boom"))
    resp = client_for(tmp_path).post("/v1/query", json=query_body())
    assert_public_error(resp, 503, "server_error")
