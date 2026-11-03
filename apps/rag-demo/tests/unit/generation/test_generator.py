"""Generator clients: bearer header (D216), native Ollama body (D219-D221, N2), retries, refusal.

Request shape and error mapping run against respx; what the real models answer is covered by the
cassette replay (``generate_smoke_622.yaml``) and the ``gpu`` tests. The embedding half of the
T1.13 ``test_client_auth.py`` lives in ``index/test_encoders.py`` (T3.4, N6.2).
"""

import json
import logging
from typing import Any

import httpx
import pytest
import respx
import yaml
from rd_support import CONFIGS, REPO, hit

from rag_demo.auth import auth_headers
from rag_demo.config import load_config, parse_config
from rag_demo.errors import ConfigError, GenerationError
from rag_demo.generation import (
    REFUSAL,
    REFUSAL_EN,
    OllamaChatGenerator,
    OpenAICompatGenerator,
    build_prompt,
    extract_citations,
    is_refusal,
    llm_client,
)
from rag_demo.generation.llm_client import build_ollama_request
from rag_demo.models import Stats

ENV = "PRUEFSTAND_CANDIDATE_API_KEY"
CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
GPU = CONFIGS / "rag.gpu.yaml"
CHAT = {
    "model": "m",
    "choices": [{"message": {"content": "Die Dokumente enthalten dazu keine Information."}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
}
NATIVE = {
    "model": "qwen3.8:27b-q8_0",
    "message": {"role": "assistant", "content": "Einen Monat (§ 622 Abs. 2 Nr. 1 BGB)."},
    "prompt_eval_count": 40,
    "eval_count": 9,
}
LLAMA_URL = "http://llm.test/v1/chat/completions"
OLLAMA_URL = "http://llm-proxy:11500/api/chat"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "BACKOFF_S", (0.0,))


def _llama() -> OpenAICompatGenerator:
    return OpenAICompatGenerator(
        load_config(CONFIGS / "rag.yaml"), "http://llm.test", stats=Stats()
    )


def _ollama(cfg_text: str | None = None) -> OllamaChatGenerator:
    cfg = load_config(GPU, CATALOGUE)
    if cfg_text:
        cfg = parse_config(cfg_text, CATALOGUE)
    return OllamaChatGenerator(cfg, "http://llm-proxy:11500", stats=Stats())


async def _ask(gen: OpenAICompatGenerator | OllamaChatGenerator) -> None:
    await gen.answer("Frage?", [hit("gii-bgb-622#0")])


def test_header_builder_cases() -> None:
    assert auth_headers(ENV, {ENV: "k1"}) == {"Authorization": "Bearer k1"}
    assert auth_headers(ENV, {}) == {}
    assert auth_headers(ENV, {ENV: ""}) == {}
    assert auth_headers(None, {ENV: "k1"}) == {}


@respx.mock
@pytest.mark.parametrize("engine", ["llama", "ollama"])
async def test_every_request_of_both_engines_carries_the_bearer_key(
    monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    monkeypatch.setenv(ENV, "k1")
    llama = respx.post(LLAMA_URL).mock(return_value=httpx.Response(200, json=CHAT))
    ollama = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=NATIVE))
    await _ask(_llama() if engine == "llama" else _ollama())
    route = llama if engine == "llama" else ollama
    assert route.calls.last.request.headers["Authorization"] == "Bearer k1"


@respx.mock
@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.parametrize("engine", ["llama", "ollama"])
async def test_no_header_when_unset_or_empty(
    monkeypatch: pytest.MonkeyPatch, value: str | None, engine: str
) -> None:
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    llama = respx.post(LLAMA_URL).mock(return_value=httpx.Response(200, json=CHAT))
    ollama = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=NATIVE))
    await _ask(_llama() if engine == "llama" else _ollama())
    route = llama if engine == "llama" else ollama
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_api_key_env_null_sends_no_header_even_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV, "k1")
    cfg = load_config(CONFIGS / "rag.yaml")
    cfg = cfg.model_copy(
        update={"generator": cfg.generator.model_copy(update={"api_key_env": None})}
    )
    route = respx.post(LLAMA_URL).mock(return_value=httpx.Response(200, json=CHAT))
    await OpenAICompatGenerator(cfg, "http://llm.test", stats=Stats()).answer(
        "Frage?", [hit("gii-bgb-622#0")]
    )
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
@pytest.mark.parametrize("engine", ["llama", "ollama"])
async def test_403_error_and_logs_never_contain_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, engine: str
) -> None:
    monkeypatch.setenv(ENV, "k1-secret-value")
    url = LLAMA_URL if engine == "llama" else OLLAMA_URL
    respx.post(url).mock(return_value=httpx.Response(403, text="bad key k1-secret-value"))
    gen = _llama() if engine == "llama" else _ollama()
    with caplog.at_level(logging.DEBUG), pytest.raises(GenerationError) as err:
        await _ask(gen)
    assert "k1-secret-value" not in str(err.value)
    assert "k1-secret-value" not in caplog.text
    assert "403" in str(err.value)


@respx.mock
async def test_native_body_goes_to_api_chat_with_catalogue_and_generation_options() -> None:
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=NATIVE))
    out = await _ollama().answer("Frist?", [hit("gii-bgb-622#0")])
    request = route.calls.last.request
    body = json.loads(request.content)
    assert "/v1/" not in str(request.url)
    assert body["model"] == "qwen3.8:27b-q8_0"
    assert body["think"] is False
    assert body["stream"] is False
    assert "keep_alive" not in body
    assert body["options"] == {
        "num_ctx": 8192,
        "top_p": 1.0,
        "temperature": 0.0,
        "seed": 1234,
        "num_predict": 256,
    }
    assert body["messages"][0]["role"] == "system"
    assert (out.prompt_tokens, out.completion_tokens) == (40, 9)
    assert out.citations == ["§ 622 Abs. 2 Nr. 1 BGB"]
    assert out.refused is False


@respx.mock
async def test_generation_section_values_become_the_sampling_options() -> None:
    data: dict[str, Any] = yaml.safe_load(GPU.read_text(encoding="utf-8"))
    data["generation"] = {"temperature": 0.7, "seed": 7, "max_tokens": 300}
    data["max_tokens"] = 300
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=NATIVE))
    await _ollama(yaml.safe_dump(data)).answer("Frist?", [hit("gii-bgb-622#0")])
    options = json.loads(route.calls.last.request.content)["options"]
    assert (options["temperature"], options["seed"], options["num_predict"]) == (0.7, 7, 300)
    assert options["num_ctx"] == 8192
    assert set(options) == {"num_ctx", "top_p", "temperature", "seed", "num_predict"}


def test_temperature_outside_the_catalogue_bounds_fails_at_load() -> None:
    data: dict[str, Any] = yaml.safe_load(GPU.read_text(encoding="utf-8"))
    data["generation"] = {**data["generation"], "temperature": 1.5}
    with pytest.raises(ConfigError, match="temperature"):
        parse_config(yaml.safe_dump(data), CATALOGUE)


def test_request_body_without_a_generation_section_is_an_error() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    with pytest.raises(GenerationError, match="generation"):
        build_ollama_request(build_prompt("Frage?", [hit("gii-bgb-622#0")], cfg), cfg)


@respx.mock
@pytest.mark.parametrize("engine", ["llama", "ollama"])
async def test_503_twice_then_200_succeeds(engine: str) -> None:
    url, ok = (LLAMA_URL, CHAT) if engine == "llama" else (OLLAMA_URL, NATIVE)
    route = respx.post(url).mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, json=ok)]
    )
    await _ask(_llama() if engine == "llama" else _ollama())
    assert route.call_count == 3


@respx.mock
async def test_503_three_times_is_a_generation_error() -> None:
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(GenerationError, match="503"):
        await _ask(_ollama())
    assert route.call_count == 3


@respx.mock
async def test_a_connection_error_is_retried() -> None:
    route = respx.post(OLLAMA_URL).mock(
        side_effect=[httpx.ConnectError("x"), httpx.Response(200, json=NATIVE)]
    )
    await _ask(_ollama())
    assert route.call_count == 2


@respx.mock
async def test_a_read_timeout_is_not_retried() -> None:
    route = respx.post(OLLAMA_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(GenerationError, match="ReadTimeout"):
        await _ask(_ollama())
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("payload", [{"unexpected": 1}, {"message": {}}])
async def test_unexpected_response_shape_is_a_generation_error(payload: dict[str, Any]) -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(GenerationError, match="unexpected shape"):
        await _ask(_ollama())


@respx.mock
async def test_non_json_body_is_a_generation_error() -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(GenerationError, match="unexpected shape"):
        await _ask(_ollama())


@respx.mock
async def test_empty_retrieval_is_refused_without_a_model_call() -> None:
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=NATIVE))
    out = await _ollama().answer("Wie hoch ist die Hundesteuer in Köln?", [])
    assert (out.answer, out.refused, out.citations) == (REFUSAL, True, [])
    assert out.prompt_chunk_ids == []
    english = await _ollama().answer("What is the dog tax in Cologne?", [])
    assert english.answer == REFUSAL_EN
    assert route.call_count == 0


@respx.mock
async def test_a_refusal_has_no_citations_and_think_is_stripped_and_counted() -> None:
    reply = dict(NATIVE)
    reply["message"] = {"content": f"<think>hm</think>{REFUSAL} Siehe § 622 BGB."}
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=reply))
    gen = _ollama()
    out = await gen.answer("Frage?", [hit("gii-bgb-622#0")])
    assert out.refused is True
    assert out.citations == []
    assert "<think>" not in out.answer
    assert gen._stats.think_stripped == 1


def test_citations_of_german_and_english_norm_references() -> None:
    assert extract_citations("Einen Monat (§ 622 Abs. 2 Nr. 1 BGB).") == ["§ 622 Abs. 2 Nr. 1 BGB"]
    assert extract_citations("Art. 6 Abs. 1 DSGVO") == ["Art. 6 Abs. 1 DSGVO"]
    assert extract_citations("see Article 6 GDPR") == ["Article 6 GDPR"]
    assert extract_citations("Keine Norm.") == []


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (REFUSAL, True),
        (f"„{REFUSAL}“", True),
        (REFUSAL_EN, True),
        (f"  {REFUSAL.upper()}", True),
        ("Einen Monat. " + REFUSAL, False),
        ("", False),
    ],
)
def test_refusal_detection(answer: str, expected: bool) -> None:  # noqa: FBT001
    assert is_refusal(answer) is expected


@respx.mock
@pytest.mark.parametrize("status", [502, 504])
async def test_502_and_504_are_not_retried(status: int) -> None:
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(status))
    with pytest.raises(GenerationError, match=str(status)):
        await _ask(_ollama())
    assert route.call_count == 1
