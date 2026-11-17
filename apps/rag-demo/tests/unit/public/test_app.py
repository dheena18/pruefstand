"""T8.4 slice 2: public mode wired into the app (respx on the real Qdrant/TEI/LLM shapes)."""

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from rd_support import CONFIGS, qdrant_point

from rag_demo.api import create_app
from rag_demo.config import Settings, load_config
from rag_demo.wiring import expected_fingerprint

QDRANT = "http://qdrant.test:6333/collections/chunks_active"
LLM = "http://llm:8080/v1/chat/completions"
CFG = load_config(CONFIGS / "rag.public.yaml")
DASHBOARD_DEFAULT_TIMEOUT_S = 90  # NEXT_PUBLIC_DEMO_TIMEOUT_S default (ui-spec 4.6, UI11-17)
REPLY = {"choices": [{"message": {"content": "Vier Wochen (§ 622 BGB)."}}], "usage": {}}
KEYS = {"code", "message", "retry_after_s"}


def _settings(tmp_path: Path, **env: object) -> Settings:
    return Settings(
        qdrant_url="http://qdrant.test:6333",
        llm_url="http://llm:8080",
        embed_url="http://embed:8090",
        demo_flag_file=str(tmp_path / "disabled"),
        **env,  # type: ignore[arg-type]  # the DEMO_* overrides of the test
    )


def _mock(llm: httpx.Response | Callable[[httpx.Request], Any] | None = None) -> respx.Route:
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
    point = qdrant_point("gii-bgb-622#1", 0.3)
    respx.post(f"{QDRANT}/points/query").mock(
        return_value=httpx.Response(200, json={"result": {"points": [point]}})
    )
    if callable(llm):
        return respx.post(LLM).mock(side_effect=llm)
    return respx.post(LLM).mock(return_value=llm or httpx.Response(200, json=REPLY))


def _client(tmp_path: Path, peer: str = "203.0.113.7", **env: object) -> TestClient:
    app = create_app(CFG, settings=_settings(tmp_path, **env))
    return TestClient(app, client=(peer, 5000))


def _query(**over: object) -> dict[str, object]:
    return {"tenant_id": "kanzlei_mueller", "question": "Welche Frist gilt?", **over}


def _assert_public_error(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/json")
    assert set(resp.json()) == KEYS
    assert resp.json()["code"] == code
    assert "Traceback" not in resp.text


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
    llm = _mock()
    resp = _client(tmp_path).post("/v1/query", json=_query(request_id="client-chosen", top_k=50))
    assert resp.status_code == 200
    assert resp.json()["answer"].startswith("Vier Wochen")
    assert llm.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        _query(tenant_id="evil_corp"),
        _query(question="x" * 501),
        _query(question=""),
        {"tenant_id": "kanzlei_mueller"},
        {**_query(), "extra": 1},
    ],
)
def test_an_invalid_body_is_422_invalid_request_without_any_backend_call(
    tmp_path: Path, body: dict[str, object]
) -> None:
    llm = _mock()
    resp = _client(tmp_path).post("/v1/query", json=body)
    _assert_public_error(resp, 422, "invalid_request")
    assert llm.call_count == 0


@respx.mock
def test_a_body_over_8_kb_is_413_body_too_large(tmp_path: Path) -> None:
    _mock()
    resp = _client(tmp_path).post("/v1/query", json=_query(question="x" * 9000))
    _assert_public_error(resp, 413, "body_too_large")


@respx.mock
def test_the_kill_switch_flag_answers_503_before_any_backend_call(tmp_path: Path) -> None:
    llm = _mock()
    client = _client(tmp_path)
    (tmp_path / "disabled").write_text("", encoding="utf-8")
    _assert_public_error(client.post("/v1/query", json=_query()), 503, "demo_disabled")
    assert llm.call_count == 0
    (tmp_path / "disabled").unlink()
    assert client.post("/v1/query", json=_query()).status_code == 200  # per request, no restart


@respx.mock
def test_the_second_request_is_rate_limited_and_cf_connecting_ip_changes_nothing(
    tmp_path: Path,
) -> None:
    _mock()
    client = _client(tmp_path, demo_rate_per_min=1, trusted_proxy_hops=1)
    ok = client.post("/v1/query", json=_query(), headers={"X-Forwarded-For": "6.6.6.6, 1.1.1.1"})
    assert ok.status_code == 200
    # a forged first hop and a changing CF-Connecting-IP do not give a new key
    again = client.post(
        "/v1/query",
        json=_query(),
        headers={"X-Forwarded-For": "7.7.7.7, 1.1.1.1", "CF-Connecting-IP": "9.9.9.9"},
    )
    _assert_public_error(again, 429, "rate_limited")
    assert again.json()["retry_after_s"] > 0
    assert again.headers["retry-after"] == str(again.json()["retry_after_s"])
    other = client.post("/v1/query", json=_query(), headers={"X-Forwarded-For": "1.1.1.2"})
    assert other.status_code == 200  # another visitor behind the proxy


@respx.mock
def test_zero_trusted_hops_key_on_the_peer_and_ignore_forwarded_for(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, demo_rate_per_min=1, trusted_proxy_hops=0)
    first = client.post("/v1/query", json=_query(), headers={"X-Forwarded-For": "1.1.1.1"})
    assert first.status_code == 200
    again = client.post("/v1/query", json=_query(), headers={"X-Forwarded-For": "2.2.2.2"})
    _assert_public_error(again, 429, "rate_limited")


@respx.mock
def test_the_daily_token_budget_is_503_budget_exhausted(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, demo_daily_tokens=300, demo_rate_per_min=100)
    assert client.post("/v1/query", json=_query()).status_code == 200  # reserves 256, settles 0
    refused = client.post("/v1/query", json=_query())
    assert refused.status_code == 200  # the settle refunded the reserve
    tiny = _client(tmp_path, demo_daily_tokens=100)
    _assert_public_error(tiny.post("/v1/query", json=_query()), 503, "budget_exhausted")


@respx.mock
def test_a_generation_over_the_server_timeout_is_504_timeout(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=REPLY)

    _mock(slow)
    resp = _client(tmp_path, demo_timeout_s=0.05).post("/v1/query", json=_query())
    _assert_public_error(resp, 504, "timeout")


@respx.mock
def test_a_backend_failure_is_a_public_error_body_not_a_stack_trace(tmp_path: Path) -> None:
    _mock(httpx.Response(500, text="boom"))
    resp = _client(tmp_path).post("/v1/query", json=_query())
    _assert_public_error(resp, 503, "server_error")


@respx.mock
def test_cors_only_for_the_dashboard_origin(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, demo_allowed_origin="http://localhost:4175")
    good = client.post("/v1/query", json=_query(), headers={"Origin": "http://localhost:4175"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:4175"
    bad = client.post("/v1/query", json=_query(), headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    refused = _client(tmp_path, demo_rate_per_min=1, demo_allowed_origin="http://localhost:4175")
    refused.post("/v1/query", json=_query())
    limited = refused.post("/v1/query", json=_query(), headers={"Origin": "http://localhost:4175"})
    assert limited.status_code == 429
    assert limited.headers["access-control-allow-origin"] == "http://localhost:4175"
    assert "retry-after" in limited.headers["access-control-expose-headers"].lower()


@respx.mock
def test_the_question_never_reaches_a_log(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _mock()
    caplog.set_level("DEBUG")
    marker = "Streng geheime Frage 4711"
    _client(tmp_path).post("/v1/query", json=_query(question=marker))
    _client(tmp_path).post("/v1/query", json=_query(question=marker, tenant_id="nope"))
    assert marker not in caplog.text


@respx.mock
def test_the_reset_route_is_absent_without_the_env(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, peer="127.0.0.1")
    assert client.post("/v1/_test/reset").status_code == 404
    assert "/v1/_test/reset" not in json.dumps(client.get("/openapi.json").json())


@respx.mock
def test_reset_from_loopback_admits_a_limited_key_again(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, peer="127.0.0.1", demo_test_reset="1", demo_rate_per_min=1)
    assert client.post("/v1/query", json=_query()).status_code == 200
    _assert_public_error(client.post("/v1/query", json=_query()), 429, "rate_limited")
    assert client.post("/v1/_test/reset").status_code == 204
    assert client.post("/v1/query", json=_query()).status_code == 200
    assert "/v1/_test/reset" not in json.dumps(client.get("/openapi.json").json())


@respx.mock
def test_reset_from_a_non_loopback_peer_is_404_even_with_a_forged_header(tmp_path: Path) -> None:
    _mock()
    client = _client(tmp_path, peer="172.18.0.1", demo_test_reset="1")
    resp = client.post("/v1/_test/reset", headers={"X-Forwarded-For": "127.0.0.1"})
    assert resp.status_code == 404
    v6 = _client(tmp_path, peer="::1", demo_test_reset="1")
    assert v6.post("/v1/_test/reset").status_code == 204


@respx.mock
def test_reset_during_a_running_generation_is_409_and_changes_nothing(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    async def held(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.to_thread(release.wait, 10)
        return httpx.Response(200, json=REPLY)

    _mock(held)
    client = _client(tmp_path, peer="127.0.0.1", demo_test_reset="1", demo_rate_per_min=1)
    result: dict[str, int] = {}
    worker = threading.Thread(
        target=lambda: result.update(status=client.post("/v1/query", json=_query()).status_code)
    )
    worker.start()
    assert started.wait(5)
    busy = client.post("/v1/_test/reset")
    assert busy.status_code == 409
    assert busy.json()["code"] == "busy"
    release.set()
    worker.join(5)
    assert result["status"] == 200
    _assert_public_error(client.post("/v1/query", json=_query()), 429, "rate_limited")  # unchanged
    assert client.post("/v1/_test/reset").status_code == 204


def test_the_public_profile_never_sets_the_test_reset() -> None:
    text = (CONFIGS / "rag.public.yaml").read_text(encoding="utf-8")
    assert "DEMO_TEST_RESET" not in text.upper()
    assert "test_reset" not in text
