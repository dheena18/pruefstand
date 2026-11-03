"""create_app: validation, /v1/info, /v1/health (collaborators stubbed at the HTTP level)."""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from rd_support import CONFIGS, REPO, SLICE

from rag_demo.api import create_app
from rag_demo.config import Settings, load_config

MANIFEST = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))
SETTINGS = Settings(
    qdrant_url="http://qdrant.test:6333",
    llm_url="http://llm.test:8080",
    embed_url="http://embed.test:8090",
    collection="slice_v1",
)
COLLECTION = {
    "result": {
        "config": {
            "metadata": {
                "corpus_version": MANIFEST["corpus_version"],
                "tenants": sorted(MANIFEST["tenants"]),
            }
        }
    }
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(load_config(CONFIGS / "rag.yaml"), settings=SETTINGS))


def _request(tenant: str = "kanzlei_mueller", question: str = "Frist?") -> dict[str, object]:
    return {"tenant_id": tenant, "question": question, "request_id": "r1"}


@respx.mock
def test_unknown_tenant_is_422_and_names_no_other_tenant(client: TestClient) -> None:
    respx.get("http://qdrant.test:6333/collections/slice_v1").mock(
        return_value=httpx.Response(200, json=COLLECTION)
    )
    resp = client.post("/v1/query", json=_request(tenant="gibt_es_nicht"))
    assert resp.status_code == 422
    assert "unknown tenant" in resp.text
    for tenant in MANIFEST["tenants"]:
        assert tenant not in resp.text


def test_overlong_question_is_422(client: TestClient) -> None:
    assert client.post("/v1/query", json=_request(question="x" * 2001)).status_code == 422
    assert client.post("/v1/query", json=_request(question="")).status_code == 422


def test_top_k_out_of_range_is_422(client: TestClient) -> None:
    for top_k in (0, 51):
        assert client.post("/v1/query", json={**_request(), "top_k": top_k}).status_code == 422


def test_unknown_request_field_is_422(client: TestClient) -> None:
    assert client.post("/v1/query", json={**_request(), "extra": 1}).status_code == 422


@respx.mock
def test_info_fields(client: TestClient) -> None:
    respx.get("http://qdrant.test:6333/collections/slice_v1").mock(
        return_value=httpx.Response(200, json=COLLECTION)
    )
    info = client.get("/v1/info").json()
    assert len(info["config_hash"]) == 16
    int(info["config_hash"], 16)
    assert info["corpus_version"] == MANIFEST["corpus_version"]
    assert info["models"]["generator_family"]
    assert info["serving"]["engine"] == "llama.cpp"
    assert set(info["serving"]) == {
        "engine",
        "engine_version",
        "quantization",
        "gpu",
        "model_sha256",
    }
    assert client.get("/v1/info").json() == info


def test_health_counters_are_ints(client: TestClient) -> None:
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    for key in ("think_stripped", "truncated_chunks", "requests"):
        assert isinstance(body["stats"][key], int)


def test_validation_error_does_not_echo_the_question(client: TestClient) -> None:
    resp = client.post("/v1/query", json=_request(question="Geheim" * 400))
    assert resp.status_code == 422
    assert "Geheim" not in resp.text


def test_overlong_ids_are_422(client: TestClient) -> None:
    assert client.post("/v1/query", json={**_request(), "request_id": "r" * 129}).status_code == 422
    assert client.post("/v1/query", json=_request(tenant="t" * 65)).status_code == 422


def test_oversized_body_is_413(client: TestClient) -> None:
    resp = client.post(
        "/v1/query",
        content=b"{" + b" " * 20_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


@respx.mock
def test_collection_metadata_without_tenants_is_503(client: TestClient) -> None:
    body = {"result": {"config": {"metadata": {"corpus_version": "slice-x"}}}}
    respx.get("http://qdrant.test:6333/collections/slice_v1").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert client.post("/v1/query", json=_request()).status_code == 503


GPU_SETTINGS = Settings(
    qdrant_url="http://qdrant.test:6333",
    collection="slice_v1",
    rag_model_catalogue=REPO / "infra" / "gpu" / "models.yaml",
    serving_engine_version="0.x",
    serving_gpu="A40",
)


@respx.mock
def test_gpu_info_serving_comes_from_the_catalogue_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_GPU0_URL", "http://127.0.0.1:11434")
    cfg = load_config(CONFIGS / "rag.gpu.yaml", catalogue_path=GPU_SETTINGS.rag_model_catalogue)
    client = TestClient(create_app(cfg, settings=GPU_SETTINGS))
    respx.get("http://qdrant.test:6333/collections/slice_v1").mock(
        return_value=httpx.Response(200, json=COLLECTION)
    )
    before = client.get("/v1/info")
    stats_before = client.get("/v1/health").json()["stats"]["requests"]
    for _ in range(3):
        client.post("/v1/query", json=_request())
    after = client.get("/v1/info")
    info = after.json()
    assert after.content == before.content
    assert info["serving"] == {
        "engine": "ollama",
        "engine_version": "0.x",
        "quantization": "Q8_0",
        "gpu": "A40",
        "model_sha256": "8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039",
    }
    assert info["models"] == {
        "generator": "ollama/qwen3.8:27b-q8_0",
        "generator_family": "qwen",
        "embed": "ollama/bge-m3",
        "rerank": "none",
    }
    health = client.get("/v1/health").json()["stats"]
    assert health["requests"] == stats_before + 3
    assert all(isinstance(v, int) for v in health.values())
