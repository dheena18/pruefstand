"""Recorder of ``fixtures/budget_calibration.json``: REAL Ollama numbers only (T3.6b, D960).

Skipped unless ``RAG_RECORD=1``. Run it on the VM under the GPU lock with the generator resident::

    RAG_RECORD=1 pruefstand-lock uv run pytest apps/rag-demo/tests/gpu/test_record_budget.py

It sends each calibration prompt once with ``num_predict: 1`` (a token count, not an answer) and
writes what Ollama reported next to the local count of the pinned generator tokenizer.
"""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from budget_cases import CASES, FIXTURE, case_messages, gpu_config, messages_sha256
from rd_support import MODEL_DIR

from rag_demo.generation.budget import count_prompt_tokens
from rag_demo.generation.llm_client import build_ollama_request
from rag_demo.index.tokens import load_token_counter

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(os.environ.get("RAG_RECORD") != "1", reason="set RAG_RECORD=1 to record"),
]
OLLAMA = os.environ.get("RECORD_OLLAMA_URL", "http://127.0.0.1:11434")
TOKENIZER = Path(os.environ.get("RAG_GENERATOR_TOKENIZER", MODEL_DIR / "tokenizers/generator.json"))


def test_record_prompt_eval_counts() -> None:
    cfg = gpu_config()
    count = load_token_counter(TOKENIZER)
    version = httpx.get(f"{OLLAMA}/api/version", timeout=30).json()["version"]
    rows = []
    for case in CASES:
        messages = case_messages(case, cfg)
        body = build_ollama_request(messages, cfg)
        body["options"]["num_predict"] = 1
        reply = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
        assert reply.status_code == 200, reply.text
        rows.append(
            {
                "name": case.name,
                "question": case.question,
                "hits": case.hits,
                "messages_sha256": messages_sha256(messages),
                "prompt_eval_count": reply.json()["prompt_eval_count"],
                "local_count": count_prompt_tokens(messages, count, cfg),
            }
        )
    data = {
        "ollama_version": version,
        "model": cfg.generator.model,
        "num_ctx": cfg.generator.options["num_ctx"],
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "tokenizer": {
            "path": str(TOKENIZER),
            "sha256": hashlib.sha256(TOKENIZER.read_bytes()).hexdigest(),
        },
        "cases": rows,
    }
    FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
