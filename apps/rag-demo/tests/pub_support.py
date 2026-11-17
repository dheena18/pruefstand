"""Shared helpers of the public-mode app tests (T8.4): respx backends, app and client builders."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
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


def settings_for(tmp_path: Path, **env: object) -> Settings:
    return Settings(
        qdrant_url="http://qdrant.test:6333",
        llm_url="http://llm:8080",
        embed_url="http://embed:8090",
        demo_flag_file=str(tmp_path / "disabled"),
        **env,  # type: ignore[arg-type]  # the DEMO_* overrides of the test
    )


def mock_backend(llm: httpx.Response | Callable[[httpx.Request], Any] | None = None) -> respx.Route:
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


def client_for(tmp_path: Path, peer: str = "203.0.113.7", **env: object) -> TestClient:
    app = create_app(CFG, settings=settings_for(tmp_path, **env))
    return TestClient(app, client=(peer, 5000))


def query_body(**over: object) -> dict[str, object]:
    return {"tenant_id": "kanzlei_mueller", "question": "Welche Frist gilt?", **over}


def assert_public_error(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/json")
    assert set(resp.json()) == KEYS
    assert resp.json()["code"] == code
    assert "Traceback" not in resp.text
