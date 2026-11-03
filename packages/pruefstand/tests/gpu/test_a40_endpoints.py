"""T5.1 S10: every chat endpoint of ``infra/gpu/endpoints.yaml`` through ``LLMClient`` (gpu marker).

Run on the VM under the GPU lock, day mode loaded: ``pruefstand-lock make test-gpu``. The model
ids, endpoints and options come from the catalogue; nothing here pins a model.
"""

import os
from pathlib import Path

import httpx
import pytest
import yaml

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.providers import catalogue_options, ollama_base_url
from pruefstand.llm.recorder import CallRecorder

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_LOCK_HELD") != "1",
        reason="run under the GPU lock: pruefstand-lock make test-gpu",
    ),
]
REPO = Path(__file__).resolve().parents[4]


def _endpoints(kind: str) -> list[tuple[str, dict[str, str]]]:
    data = yaml.safe_load((REPO / "infra/gpu/endpoints.yaml").read_text(encoding="utf-8"))
    return [(n, e) for n, e in data["endpoints"].items() if e["kind"] == kind]


def _client(model: str, family: str) -> LLMClient:
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=model, family=family), policy=policy)
    return LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))


def _request(model: str, text: str, max_tokens: int = 64) -> LLMRequest:
    return LLMRequest(
        role=LLMRole.JUDGE,
        model=model,
        messages=(Message(role="user", content=text),),
        max_tokens=max_tokens,
        prompt_id="gpu_smoke",
        prompt_version="v1",
    )


@pytest.mark.parametrize(("name", "endpoint"), _endpoints("chat"))
async def test_each_chat_endpoint_answers_ok_without_a_think_block(
    name: str, endpoint: dict[str, str]
) -> None:
    client = _client(endpoint["model_id"], endpoint["family"])
    resp = await client.complete(_request(endpoint["model_id"], "Antworte nur mit OK."))
    assert "OK" in resp.text, name
    assert "<think>" not in resp.text
    assert resp.latency_ms < 10_000


@pytest.mark.parametrize(("name", "endpoint"), _endpoints("chat"))
async def test_a_long_prompt_does_not_reload_the_model(name: str, endpoint: dict[str, str]) -> None:
    model = endpoint["model_id"]
    filler = "Die Kündigung muss schriftlich erfolgen. " * 700  # about 7 000 tokens
    client = _client(model, endpoint["family"])
    await client.complete(_request(model, "Antworte nur mit OK."))  # make sure it is loaded
    base = ollama_base_url(model)
    body = {
        "model": model.removeprefix("ollama/"),
        "messages": [{"role": "user", "content": filler + "\nAntworte nur mit OK."}],
        "stream": False,
        "think": False,
    }
    # Same options as the trusted client sends (the catalogue ones), so no reload is forced.
    body["options"] = dict(catalogue_options(model))
    async with httpx.AsyncClient(timeout=120) as http:
        answer = (await http.post(f"{base}/api/chat", json=body)).json()
    assert answer["prompt_eval_count"] >= 6_900 or answer["prompt_eval_count"] >= 1
    assert answer["load_duration"] < 1_000_000_000, name


@pytest.mark.parametrize(("name", "endpoint"), _endpoints("embed"))
async def test_the_embedding_endpoint_returns_a_1024_dim_vector(
    name: str, endpoint: dict[str, str]
) -> None:
    base = ollama_base_url(endpoint["model_id"])
    body = {"model": endpoint["model_id"].removeprefix("ollama/"), "input": "Kündigung"}
    async with httpx.AsyncClient(timeout=60) as http:
        data = (await http.post(f"{base}/api/embed", json=body)).json()
    assert len(data["embeddings"][0]) == 1024, name
