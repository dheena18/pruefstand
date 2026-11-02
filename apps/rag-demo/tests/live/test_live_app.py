"""Against the running `live` stack (T1.13): smoke questions, tenant isolation, info/health, schema.

Needs ``make up PROFILES="core live dev"`` and ``make index-slice``; the app URL comes from
``RAG_DEMO_URL`` (default ``http://127.0.0.1:$RAG_DEMO_HOST_PORT``).
"""

import json
import os
import re
import statistics
import time
import uuid

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from rd_support import APP_DIR, REPO

pytestmark = pytest.mark.live
URL = os.environ.get(
    "RAG_DEMO_URL", f"http://127.0.0.1:{os.environ.get('RAG_DEMO_HOST_PORT', '8000')}"
)
QUESTIONS = yaml.safe_load((APP_DIR / "tests" / "live" / "smoke_questions.yaml").read_text("utf-8"))
OPENAPI = yaml.safe_load((REPO / "schemas" / "target-api-v1.openapi.yaml").read_text("utf-8"))
P95_LIMIT_S = 15.0


def ask(tenant: str, question: str) -> tuple[dict[str, object], float]:
    started = time.monotonic()
    resp = httpx.post(
        f"{URL}/v1/query",
        json={"tenant_id": tenant, "question": question, "request_id": uuid.uuid4().hex},
        timeout=120,
    )
    elapsed = time.monotonic() - started
    assert resp.status_code == 200, resp.text
    return resp.json(), elapsed


def cites(body: dict[str, object], expect: str) -> bool:
    pattern = re.escape(expect).replace(r"\ ", r"\s+") + r"(?!\d)"
    text = f"{body['answer']} {' '.join(map(str, body['citations']))}"  # type: ignore[call-overload]
    return re.search(pattern, text) is not None


def test_smoke_questions_cite_the_expected_norm_within_the_latency_budget() -> None:
    cited = 0
    latencies: list[float] = []
    for row in QUESTIONS["smoke"]:
        body, elapsed = ask(row["tenant"], row["question"])
        latencies.append(elapsed)
        assert "<think>" not in str(body["answer"])
        assert body["chunks"]
        cited += cites(body, row["expect"])
    p95 = statistics.quantiles(latencies, n=20)[-1]
    print(f"smoke: cited {cited}/10, p95 {p95:.1f} s")  # noqa: T201
    assert cited >= 6
    assert p95 <= P95_LIMIT_S


def test_bergmann_question_from_kanzlei_mueller_leaks_nothing() -> None:
    body, _ = ask(
        "kanzlei_mueller", "Wie lang ist die Kündigungsfrist im Rahmenvertrag mit Firma Bergmann?"
    )
    assert "47 Tage" not in str(body["answer"])
    tenants = {c["tenant_id"] for c in body["chunks"]}  # type: ignore[attr-defined]
    assert tenants <= {"kanzlei_mueller", "shared_public"}


def test_info_is_static_and_health_counters_grow() -> None:
    before = httpx.get(f"{URL}/v1/info", timeout=10).json()
    stats_before = httpx.get(f"{URL}/v1/health", timeout=10).json()["stats"]
    for row in QUESTIONS["smoke"][:3]:
        ask(row["tenant"], row["question"])
    assert httpx.get(f"{URL}/v1/info", timeout=10).json() == before
    stats_after = httpx.get(f"{URL}/v1/health", timeout=10).json()["stats"]
    assert stats_after["requests"] == stats_before["requests"] + 3
    assert set(before["serving"]) == {
        "engine",
        "engine_version",
        "quantization",
        "gpu",
        "model_sha256",
    }
    assert before["serving"]["gpu"].startswith("cpu:")


def test_responses_validate_against_the_target_api_schema() -> None:
    schemas = OPENAPI["components"]["schemas"]
    resolver = {"components": OPENAPI["components"]}

    def check(name: str, instance: object) -> None:
        schema = {"$ref": f"#/components/schemas/{name}", **resolver}
        Draft202012Validator(schema).validate(instance)

    body, _ = ask("kanzlei_mueller", QUESTIONS["smoke"][0]["question"])
    check("QueryResponse", body)
    check("InfoResponse", httpx.get(f"{URL}/v1/info", timeout=10).json())
    check("HealthResponse", httpx.get(f"{URL}/v1/health", timeout=10).json())
    assert "RetrievedChunk" in schemas
    assert all(c["used_in_prompt"] is True for c in body["chunks"])  # type: ignore[attr-defined]
    json.dumps(body)
