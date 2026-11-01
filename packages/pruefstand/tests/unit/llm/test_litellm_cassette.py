"""LiteLLMBackend against recorded real exchanges, plus the pure request builder."""

import pytest
from testsupport.llm_scenarios import TEST_API_BASE, TEST_MODEL, echo_request

from pruefstand.core.errors import LLMError
from pruefstand.llm.backends.litellm import LiteLLMBackend, completion_kwargs, strip_think
from pruefstand.llm.recorder import COLUMNS


def _backend(model: str = TEST_MODEL) -> LiteLLMBackend:
    return LiteLLMBackend(model, api_base=TEST_API_BASE, api_key_env=None, timeout_s=30)


@pytest.mark.default_cassette("echo_ok.yaml")
@pytest.mark.vcr
async def test_replayed_echo_maps_usage_cost_and_latency() -> None:
    resp = await _backend().acomplete(echo_request())
    assert resp.text.strip()
    assert resp.usage.prompt_tokens > 0
    assert resp.usage.completion_tokens > 0
    assert resp.cost_usd == 0.0
    assert resp.latency_ms >= 0
    assert resp.provider == "openai_compatible_local"
    assert resp.model == TEST_MODEL
    assert resp.cached is False


@pytest.mark.default_cassette("server_503.yaml")
@pytest.mark.vcr
async def test_replayed_503_is_transient_with_status() -> None:
    with pytest.raises(LLMError) as info:
        await _backend().acomplete(echo_request())
    assert info.value.transient is True
    assert info.value.status == 503


def _kwargs(model: str) -> dict[str, object]:
    req = echo_request().model_copy(update={"model": model})
    return completion_kwargs(req, api_base="http://localhost:8080/v1", api_key="k", timeout_s=12.0)


def test_qwen3_gets_thinking_disabled_in_extra_body() -> None:
    kwargs = _kwargs("openai_compatible_local/qwen3-1.7b")
    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert kwargs["model"] == "openai/qwen3-1.7b"


def test_qwen25_has_no_extra_body() -> None:
    assert "extra_body" not in _kwargs("openai_compatible_local/qwen2.5-0.5b-instruct")


def test_request_parameters_are_forwarded() -> None:
    req = echo_request(temperature=0.3, max_tokens=7, seed=5)
    kwargs = completion_kwargs(req, api_base="http://x/v1", api_key="k", timeout_s=9.0)
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 7
    assert kwargs["seed"] == 5
    assert kwargs["timeout"] == 9.0
    assert kwargs["num_retries"] == 0
    assert kwargs["api_base"] == "http://x/v1"
    assert "response_format" not in kwargs
    assert kwargs["messages"][0]["role"] == "system"  # type: ignore[index]  # list of dicts


def test_json_mode_sets_response_format() -> None:
    req = echo_request().model_copy(update={"response_format": "json"})
    kwargs = completion_kwargs(req, api_base="http://x/v1", api_key="k", timeout_s=9.0)
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<think>x</think>Antwort", ("Antwort", True)),
        ("<think>\nlange Überlegung\n</think>\n\nAntwort", ("Antwort", True)),
        ("Antwort", ("Antwort", False)),
        ("Antwort <think>mitten</think>", ("Antwort <think>mitten</think>", False)),
        ("<think>offen", ("<think>offen", False)),
    ],
)
def test_strip_think(text: str, expected: tuple[str, bool]) -> None:
    assert strip_think(text) == expected


def test_recorder_columns_do_not_include_think_flag() -> None:
    assert "think_stripped" not in COLUMNS
    assert len(COLUMNS) == 13


async def test_wrong_port_is_transient() -> None:
    backend = LiteLLMBackend(
        TEST_MODEL, api_base="http://127.0.0.1:1/v1", api_key_env=None, timeout_s=5
    )
    with pytest.raises(LLMError) as info:
        await backend.acomplete(echo_request())
    assert info.value.transient is True


async def test_missing_token_names_the_variable_but_no_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRUEFSTAND_GH_MODELS_TOKEN", raising=False)
    backend = LiteLLMBackend(
        "github/openai/gpt-4o-mini",
        api_base=None,
        api_key_env="PRUEFSTAND_GH_MODELS_TOKEN",
        timeout_s=5,
    )
    req = echo_request().model_copy(update={"model": "github/openai/gpt-4o-mini"})
    with pytest.raises(LLMError, match="PRUEFSTAND_GH_MODELS_TOKEN") as info:
        await backend.acomplete(req)
    assert info.value.transient is False
