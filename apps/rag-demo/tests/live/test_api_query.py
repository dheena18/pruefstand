"""`/v1/query` against the running `live` stack: real retriever, real generator (T3.6).

Needs ``make up PROFILES="core live dev" WAIT=1`` and ``make index-slice``; the app URL comes from
``RAG_DEMO_URL``. The prompt-chunk equality (chunks with ``used_in_prompt`` = chunks of the built
prompt, same ids and order) is asserted offline in ``unit/test_api_generation.py`` against the
request the generator really sends.
"""

import os
import uuid

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from rd_support import REPO

pytestmark = pytest.mark.live
URL = os.environ.get(
    "RAG_DEMO_URL", f"http://127.0.0.1:{os.environ.get('RAG_DEMO_HOST_PORT', '8000')}"
)
OPENAPI = yaml.safe_load((REPO / "schemas" / "target-api-v1.openapi.yaml").read_text("utf-8"))
SERVING_KEYS = {"engine", "engine_version", "quantization", "gpu", "model_sha256"}
ANSWERABLE = "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"
UNANSWERABLE = "Wie hoch ist die Hundesteuer in Köln?"


def ask(question: str) -> dict[str, object]:
    resp = httpx.post(
        f"{URL}/v1/query",
        json={"tenant_id": "kanzlei_mueller", "question": question, "request_id": uuid.uuid4().hex},
        timeout=120,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def test_response_validates_and_every_chunk_says_whether_the_prompt_held_it() -> None:
    body = ask(ANSWERABLE)
    schema = {"$ref": "#/components/schemas/QueryResponse", "components": OPENAPI["components"]}
    Draft202012Validator(schema).validate(body)
    chunks: list[dict[str, object]] = body["chunks"]  # type: ignore[assignment]  # json
    assert [c["rank"] for c in chunks] == list(range(1, len(chunks) + 1))
    flags = [bool(c["used_in_prompt"]) for c in chunks]
    assert all(isinstance(c["used_in_prompt"], bool) for c in chunks)
    assert flags == sorted(flags, reverse=True)  # prompted chunks first, extras after


def test_an_unanswerable_question_sets_the_refused_flag() -> None:
    body = ask(UNANSWERABLE)
    assert isinstance(body["refused"], bool)
    assert "<think>" not in str(body["answer"])


def test_info_is_byte_identical_and_health_requests_grow_by_three() -> None:
    before = httpx.get(f"{URL}/v1/info", timeout=10)
    requests_before = httpx.get(f"{URL}/v1/health", timeout=10).json()["stats"]["requests"]
    for _ in range(3):
        ask(ANSWERABLE)
    after = httpx.get(f"{URL}/v1/info", timeout=10)
    assert after.content == before.content
    assert set(after.json()["serving"]) == SERVING_KEYS
    assert httpx.get(f"{URL}/v1/health", timeout=10).json()["stats"]["requests"] == (
        requests_before + 3
    )
