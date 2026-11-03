"""The tier-2 generator against the real A40 Ollama through the dev stack (T3.6, marker gpu).

Run it on the VM under the GPU lock with day mode up and the stack on the dev ports (see
``test_gpu_app.py``); the query tests need the bge-m3 index (``RAG_GPU_INDEXED=1``).
"""

import os
import re
import uuid

import httpx
import pytest

pytestmark = pytest.mark.gpu
URL = os.environ.get(
    "RAG_DEMO_URL", f"http://127.0.0.1:{os.environ.get('RAG_DEMO_HOST_PORT', '18000')}"
)
needs_index = pytest.mark.skipif(
    os.environ.get("RAG_GPU_INDEXED") != "1", reason="needs the bge-m3 index; RAG_GPU_INDEXED=1"
)
KUENDIGUNG = (
    "Welche Kündigungsfrist gilt für den Arbeitgeber, wenn das Arbeitsverhältnis zwei Jahre "
    "bestanden hat?"
)


def ask(question: str) -> dict[str, object]:
    resp = httpx.post(
        f"{URL}/v1/query",
        json={"tenant_id": "kanzlei_mueller", "question": question, "request_id": uuid.uuid4().hex},
        timeout=600,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


@needs_index
def test_notice_period_answer_names_one_month_and_cites_622() -> None:
    body = ask(KUENDIGUNG)
    assert "einen Monat" in str(body["answer"])
    assert any(re.match(r"§\s*622", c) for c in body["citations"])  # type: ignore[attr-defined]  # json
    assert body["refused"] is False
    assert "<think>" not in str(body["answer"])


@needs_index
def test_unanswerable_question_is_refused() -> None:
    body = ask("Wie hoch ist die Hundesteuer in Köln?")
    assert body["refused"] is True
    assert body["citations"] == []


@needs_index
def test_prompt_overflow_stays_zero_on_the_smoke_questions() -> None:
    ask(KUENDIGUNG)
    stats = httpx.get(f"{URL}/v1/health", timeout=30).json()["stats"]
    assert stats["prompt_overflow"] == 0, "calibrate the local count (D623) before trusting this"
