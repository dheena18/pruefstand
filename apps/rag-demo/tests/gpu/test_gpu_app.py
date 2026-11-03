"""Against the tier-2 dev stack on the VM (T3.2): Ollama on the A40s through the tunnel.

Run it under the GPU lock with day mode loaded and the stack up on the dev ports (Y6.5):

    make up COMPOSE_FILES="infra/gpu/compose.gpu.yml infra/gpu/compose.rag-demo.yml" \
        PROFILES="gpu dev" SERVICES=rag-demo-dev
    uv run pytest -m gpu apps/rag-demo/tests/gpu -v

The app URL comes from ``RAG_DEMO_URL`` (default: ``127.0.0.1:$RAG_DEMO_HOST_PORT``, 18000 with
the dev offset). The query tests need the slice indexed with ``bge-m3`` (T3.4); they run with
``RAG_GPU_INDEXED=1`` and skip otherwise.
"""

import os
import re
import uuid

import httpx
import pytest
import yaml
from rd_support import APP_DIR, BERGMANN

pytestmark = pytest.mark.gpu
URL = os.environ.get(
    "RAG_DEMO_URL", f"http://127.0.0.1:{os.environ.get('RAG_DEMO_HOST_PORT', '18000')}"
)
QUESTIONS = yaml.safe_load((APP_DIR / "tests" / "live" / "smoke_questions.yaml").read_text("utf-8"))
INDEXED = os.environ.get("RAG_GPU_INDEXED") == "1"
needs_index = pytest.mark.skipif(
    not INDEXED, reason="needs the bge-m3 index (T3.4); RAG_GPU_INDEXED=1"
)


def ask(tenant: str, question: str) -> dict[str, object]:
    resp = httpx.post(
        f"{URL}/v1/query",
        json={"tenant_id": tenant, "question": question, "request_id": uuid.uuid4().hex},
        timeout=300,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def cites(body: dict[str, object], expect: str) -> bool:
    pattern = re.escape(expect).replace(r"\ ", r"\s+") + r"(?!\d)"
    text = f"{body['answer']} {' '.join(map(str, body['citations']))}"  # type: ignore[call-overload]  # body is a JSON dict[str, object]; citations is a list
    return re.search(pattern, text) is not None


def test_info_reports_the_catalogue_models_and_serving() -> None:
    info = httpx.get(f"{URL}/v1/info", timeout=30).json()
    assert info["serving"]["engine"] == "ollama"
    assert info["serving"]["gpu"] == "A40"
    assert len(info["serving"]["model_sha256"]) == 64
    assert info["models"]["generator"] == "ollama/qwen3.8:27b-q8_0"
    assert info["models"]["generator_family"] == "qwen"
    assert info["models"]["embed"] == "ollama/bge-m3"


@needs_index
def test_smoke_questions_cite_the_expected_norm() -> None:
    cited = 0
    for row in QUESTIONS["smoke"]:
        body = ask(row["tenant"], row["question"])
        assert "<think>" not in str(body["answer"])
        cited += cites(body, row["expect"])
    assert cited >= 8


@needs_index
def test_bergmann_question_from_kanzlei_mueller_returns_no_foreign_chunk() -> None:
    body = ask("kanzlei_mueller", BERGMANN)
    tenants = {c["tenant_id"] for c in body["chunks"]}  # type: ignore[attr-defined]
    assert tenants <= {"kanzlei_mueller", "shared_public"}
