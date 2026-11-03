"""D216 bearer header for the generator client (pure builder + respx); the embedding half lives in
index/test_encoders.py (T3.4, N6.2)."""

import json
import logging

import httpx
import pytest
import respx
from rd_support import CONFIGS, hit

from rag_demo.auth import auth_headers
from rag_demo.config import load_config
from rag_demo.errors import GenerationError
from rag_demo.generate import OpenAICompatGenerator
from rag_demo.models import Stats

ENV = "PRUEFSTAND_CANDIDATE_API_KEY"
CHAT = {
    "model": "m",
    "choices": [{"message": {"content": "Die Dokumente enthalten dazu keine Information."}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
}


def test_header_builder_cases() -> None:
    assert auth_headers(ENV, {ENV: "k1"}) == {"Authorization": "Bearer k1"}
    assert auth_headers(ENV, {}) == {}
    assert auth_headers(ENV, {ENV: ""}) == {}
    assert auth_headers(None, {ENV: "k1"}) == {}


@respx.mock
async def test_generator_request_carries_the_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "k1")
    cfg = load_config(CONFIGS / "rag.yaml")
    route = respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=CHAT)
    )
    await OpenAICompatGenerator(cfg, "http://llm.test", stats=Stats()).answer(
        "Frage?", [hit("gii-bgb-622#0")]
    )
    assert route.calls.last.request.headers["Authorization"] == "Bearer k1"
    assert json.loads(route.calls.last.request.content)["messages"]


@pytest.mark.parametrize("value", [None, ""])
@respx.mock
async def test_no_header_when_unset_or_empty(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    cfg = load_config(CONFIGS / "rag.yaml")
    gen_route = respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=CHAT)
    )
    await OpenAICompatGenerator(cfg, "http://llm.test", stats=Stats()).answer(
        "Frage?", [hit("gii-bgb-622#0")]
    )
    assert "Authorization" not in gen_route.calls.last.request.headers


@respx.mock
async def test_api_key_env_null_sends_no_header_even_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV, "k1")
    cfg = load_config(CONFIGS / "rag.yaml")
    cfg = cfg.model_copy(
        update={"generator": cfg.generator.model_copy(update={"api_key_env": None})}
    )
    route = respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=CHAT)
    )
    await OpenAICompatGenerator(cfg, "http://llm.test", stats=Stats()).answer(
        "Frage?", [hit("gii-bgb-622#0")]
    )
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_403_error_and_logs_never_contain_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(ENV, "k1-secret-value")
    cfg = load_config(CONFIGS / "rag.yaml")
    respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(403, text="bad key k1-secret-value")
    )
    gen = OpenAICompatGenerator(cfg, "http://llm.test", stats=Stats())
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as err:
        await gen.answer("Frage?", [hit("gii-bgb-622#0")])
    assert "k1-secret-value" not in str(err.value)
    assert "k1-secret-value" not in caplog.text
    assert "403" in str(err.value)
