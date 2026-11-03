"""Qwen3 thinking off, Ollama native API shape, catalogue options (D95, R11 D219-D221, R12 D252)."""

from pathlib import Path

import pytest
import yaml
from testsupport.gpu_files import (
    OPTIONS,
    SHIPPED_CATALOGUE,
    SHIPPED_ENDPOINTS,
    write_catalogue,
    write_endpoints,
)
from testsupport.llm_scenarios import echo_request
from testsupport.loopback_script import serve_script

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.litellm import LiteLLMBackend, litellm_model, strip_think
from pruefstand.llm.factory import build_backend

GEN = "ollama/qwen3.8:27b-q8_0"
JUDGE = "ollama/gemma3:12b"
FIVE = {"num_ctx", "num_predict", "temperature", "seed", "top_p"}


def _req(model: str, **update: object) -> LLMRequest:
    return echo_request().model_copy(update={"model": model, **update})


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))


def _shipped_options(model_id: str) -> dict[str, object]:
    data = yaml.safe_load(SHIPPED_CATALOGUE.read_text(encoding="utf-8"))
    return next(m["options"] for m in data["models"] if m["id"] == model_id)


async def test_the_generator_goes_to_api_chat_with_think_false_and_catalogue_options(
    shipped: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script() as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU0_URL", origin)
        backend = build_backend(ModelRef(id=GEN, family="qwen"), policy=LLMPolicyConfig())
        resp = await backend.acomplete(_req(GEN, temperature=0.7, max_tokens=33))
    assert resp.text == "OK"
    (seen,) = state.seen
    assert seen.path == "/api/chat"
    assert seen.body["model"] == GEN.removeprefix("ollama/")
    assert seen.body["think"] is False
    assert seen.body["options"] == _shipped_options(GEN)
    assert "keep_alive" not in seen.body
    assert "chat_template_kwargs" not in seen.body


async def test_a_non_qwen_ollama_model_sends_its_own_options_and_think_false(
    shipped: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script() as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
        await backend.acomplete(_req(JUDGE))
    (seen,) = state.seen
    assert seen.path == "/api/chat"
    assert seen.body["think"] is False
    options = seen.body["options"]
    assert isinstance(options, dict)
    assert set(options) == FIVE
    assert options == _shipped_options(JUDGE)
    assert "chat_template_kwargs" not in seen.body


async def test_json_requests_use_the_native_format_field(
    shipped: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script(content='{"a": 1}') as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
        await backend.acomplete(_req(JUDGE, response_format="json"))
    assert state.seen[0].body["format"] == "json"


async def test_a_temp_catalogue_decides_the_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue = write_catalogue(tmp_path / "models.yaml", {JUDGE: OPTIONS})
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    with serve_script() as (origin, state):
        endpoints = write_endpoints(tmp_path / "ep.yaml", {"judge": ("T_URL", JUDGE)})
        monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
        monkeypatch.setenv("T_URL", origin)
        backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
        await backend.acomplete(_req(JUDGE))
    assert state.seen[0].body["options"] == OPTIONS
    assert not state.seen[0].path.startswith("/v1")


async def test_an_id_missing_from_the_catalogue_fails_at_request_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue = write_catalogue(tmp_path / "models.yaml", {"ollama/other:1b": OPTIONS})
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))
    monkeypatch.setenv("OLLAMA_GPU1_URL", "http://127.0.0.1:9")
    backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
    assert isinstance(backend, LiteLLMBackend)  # the factory never reads the catalogue
    with pytest.raises(ConfigError, match=JUDGE.replace("/", "/")):
        await backend.acomplete(_req(JUDGE))


async def test_a_catalogue_id_without_the_ollama_prefix_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump({"models": [{"id": "gemma3:12b", "engine": "ollama", "options": OPTIONS}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(path))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))
    monkeypatch.setenv("OLLAMA_GPU1_URL", "http://127.0.0.1:9")
    backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
    with pytest.raises(ConfigError):
        await backend.acomplete(_req(JUDGE))


def test_the_litellm_model_is_ollama_chat_never_v1() -> None:
    assert litellm_model(ModelRef(id=GEN, family="qwen")) == "ollama_chat/qwen3.8:27b-q8_0"
    with pytest.raises(ConfigError):
        litellm_model(ModelRef(id="ollama_chat/x", family="qwen"))


async def test_llamacpp_qwen3_disables_thinking_through_the_template_kwargs() -> None:
    model = "openai_compatible_local/qwen3-4b"
    with serve_script() as (origin, state):
        backend = LiteLLMBackend(model, api_base=f"{origin}/v1", api_key_env=None, timeout_s=30)
        await backend.acomplete(_req(model))
        other = "openai_compatible_local/gemma-x"
        other_backend = LiteLLMBackend(
            other, api_base=f"{origin}/v1", api_key_env=None, timeout_s=30
        )
        await other_backend.acomplete(_req(other))
    assert state.seen[0].body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in state.seen[1].body


def test_a_leading_think_block_is_stripped_and_flagged() -> None:
    assert strip_think("<think>Überlegung</think>\n\nAntwort") == ("Antwort", True)
    assert strip_think("Antwort <think>x</think>") == ("Antwort <think>x</think>", False)


async def test_the_backend_counts_stripped_think_blocks(
    shipped: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script(content="<think>x</think>Antwort") as (origin, _):
        monkeypatch.setenv("OLLAMA_GPU0_URL", origin)
        backend = build_backend(ModelRef(id=GEN, family="qwen"), policy=LLMPolicyConfig())
        assert isinstance(backend, LiteLLMBackend)
        resp = await backend.acomplete(_req(GEN))
    assert resp.text == "Antwort"
    assert backend.think_stripped == 1
