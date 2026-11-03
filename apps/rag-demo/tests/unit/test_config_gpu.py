"""Tier-2 profile of rag-demo: catalogue-validated config, endpoint rules, Ollama request (T3.2)."""

import json
from typing import Any

import httpx
import pytest
import respx
import yaml
from pydantic import ValidationError
from rd_support import CONFIGS, REPO, hit

from rag_demo.api import create_app
from rag_demo.config import Settings, config_hash, load_config, parse_config
from rag_demo.errors import ConfigError
from rag_demo.generation import OllamaChatGenerator, build_prompt
from rag_demo.generation.llm_client import build_ollama_request
from rag_demo.models import Stats

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
GPU = CONFIGS / "rag.gpu.yaml"
BUG_FIELDS = {
    "tenant_filter_post_topk": "tenant_filter",
    "shared_public_unfiltered": "shared_public_merge",
    "no_citations": "prompt_file",
    "no_refusal": "prompt_file",
    "answer_language_en": "answer_language",
    "injection_guard_off": "injection_guard",
    "system_prompt_guard_off": "system_prompt_guard",
    "top_k_1": "top_k",
    "reranker_off": "reranker",
}


def _data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(GPU.read_text(encoding="utf-8"))
    return loaded


def _parse(data: dict[str, Any]) -> Any:
    return parse_config(yaml.safe_dump(data), catalogue_path=CATALOGUE)


def _flat(data: dict[str, object], prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def _with_generator(**changes: Any) -> dict[str, Any]:
    data = _data()
    data["generator"] = {**data["generator"], **changes}
    return data


def test_gpu_profile_loads_with_the_catalogue() -> None:
    cfg = load_config(GPU, catalogue_path=CATALOGUE)
    assert cfg.profile == "gpu"
    assert cfg.generator.engine == "ollama"
    assert cfg.generator.catalogue_id == "ollama/qwen3.8:27b-q8_0"
    assert cfg.generator.options["num_ctx"] == 8192
    assert cfg.generator.enable_thinking is False
    assert cfg.embed.engine == "ollama"
    assert cfg.embed.catalogue_id == "ollama/bge-m3"
    assert cfg.reranker == "on"
    assert cfg.rerank.endpoint_env == "RERANK_URL"
    assert (cfg.rerank.top_n, cfg.rerank.on_retrieve) == (10, True)


def test_gpu_profile_loads_with_the_endpoint_variables_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("OLLAMA_GPU0_URL", "LLM_PROXY_URL", "RERANK_URL"):
        monkeypatch.delenv(name, raising=False)
    assert load_config(GPU, catalogue_path=CATALOGUE).generator.endpoint_env == "OLLAMA_GPU0_URL"


def test_catalogue_path_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_MODEL_CATALOGUE", str(CATALOGUE))
    assert load_config(GPU).profile == "gpu"
    monkeypatch.delenv("RAG_MODEL_CATALOGUE")
    with pytest.raises(ConfigError, match="RAG_MODEL_CATALOGUE"):
        load_config(GPU)


def test_live_profile_ignores_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_MODEL_CATALOGUE", raising=False)
    assert load_config(CONFIGS / "rag.yaml").profile == "live"


def test_unknown_catalogue_id_names_the_id_and_the_path() -> None:
    data = _with_generator(catalogue_id="ollama/gibt-es-nicht")
    with pytest.raises(ConfigError) as err:
        _parse(data)
    assert "ollama/gibt-es-nicht" in str(err.value)
    assert str(CATALOGUE) in str(err.value)


def test_bare_tag_as_catalogue_id_names_d221() -> None:
    with pytest.raises(ValidationError, match="D221"):
        _parse(_with_generator(catalogue_id="qwen3.8:27b-q8_0"))


def test_embed_engine_ollama_requires_an_ollama_id() -> None:
    data = _data()
    data["embed"] = {**data["embed"], "catalogue_id": "cpu/bge-reranker-v2-m3"}
    with pytest.raises(ValidationError, match="D221"):
        _parse(data)


def test_num_ctx_that_differs_from_the_catalogue_is_an_error() -> None:
    with pytest.raises(ConfigError, match="num_ctx"):
        _parse(_with_generator(options={"num_ctx": 4096, "top_p": 1.0}))


def test_ollama_generator_needs_num_ctx() -> None:
    with pytest.raises(ValidationError, match="num_ctx"):
        _parse(_with_generator(options={}))


def test_temperature_inside_the_bounds_loads_and_outside_names_the_bounds() -> None:
    data = _data()
    data["generation"] = {**data["generation"], "temperature": 0.7}
    assert _parse(data).generation.temperature == 0.7
    data["generation"] = {**data["generation"], "temperature": 1.5}
    with pytest.raises(ConfigError, match=r"temperature.*\[0\.0, 1\.0\]"):
        _parse(data)


def test_max_tokens_beyond_num_predict_bound_is_an_error() -> None:
    data = _data()
    data["generation"] = {**data["generation"], "max_tokens": 513}
    data["max_tokens"] = 513
    with pytest.raises(ConfigError, match="max_tokens"):
        _parse(data)


def test_ollama_generator_needs_the_generation_section() -> None:
    data = _data()
    del data["generation"]
    with pytest.raises(ValidationError, match="generation"):
        _parse(data)


def test_thinking_on_is_rejected_for_ollama() -> None:
    with pytest.raises(ValidationError, match="thinking"):
        _parse(_with_generator(enable_thinking=True))


@pytest.mark.parametrize(
    "url",
    ["https://models.github.ai/inference", "https://api.openai.com/v1", "http://10.0.0.5:11434"],
)
def test_hosted_generator_endpoint_is_rejected_naming_w315(url: str) -> None:
    data = _with_generator(base_url=url)
    del data["generator"]["endpoint_env"]
    with pytest.raises(ValidationError, match=r"W3\.15"):
        _parse(data)


@pytest.mark.parametrize("url", ["http://llm-proxy:11500", "http://127.0.0.1:11434"])
def test_internal_ollama_endpoints_are_accepted(url: str) -> None:
    data = _with_generator(base_url=url)
    del data["generator"]["endpoint_env"]
    assert _parse(data).generator.base_url == url


def test_llama_cpp_endpoint_with_v1_is_accepted() -> None:
    cfg = parse_config(
        (CONFIGS / "rag.yaml")
        .read_text(encoding="utf-8")
        .replace(
            "  model: qwen2.5-0.5b-instruct-q4_k_m\n",
            "  model: qwen2.5-0.5b-instruct-q4_k_m\n  base_url: http://127.0.0.1:8080/v1\n",
        )
    )
    assert cfg.generator.base_url == "http://127.0.0.1:8080/v1"


def test_ollama_endpoint_with_v1_names_d219() -> None:
    data = _with_generator(base_url="http://127.0.0.1:11434/v1")
    del data["generator"]["endpoint_env"]
    with pytest.raises(ValidationError, match="D219"):
        _parse(data)


def test_base_url_and_endpoint_env_are_exclusive() -> None:
    with pytest.raises(ValidationError, match="base_url"):
        _parse(_with_generator(base_url="http://127.0.0.1:11434"))


def test_missing_endpoint_variable_is_a_startup_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_GPU0_URL", raising=False)
    cfg = load_config(GPU, catalogue_path=CATALOGUE)
    with pytest.raises(ConfigError, match="OLLAMA_GPU0_URL"):
        create_app(cfg, settings=Settings(rag_model_catalogue=CATALOGUE))


@pytest.mark.parametrize("url", ["https://api.openai.com", "http://llm-proxy:11500/v1"])
def test_env_provided_endpoint_is_checked_at_startup(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("OLLAMA_GPU0_URL", url)
    cfg = load_config(GPU, catalogue_path=CATALOGUE)
    with pytest.raises(ConfigError, match=r"W3\.15|D219"):
        create_app(cfg, settings=Settings(rag_model_catalogue=CATALOGUE))


def test_api_key_env_default_and_rerank_has_no_key() -> None:
    cfg = load_config(GPU, catalogue_path=CATALOGUE)
    assert cfg.generator.api_key_env == "PRUEFSTAND_CANDIDATE_API_KEY"
    assert cfg.embed.api_key_env == "PRUEFSTAND_CANDIDATE_API_KEY"
    data = _data()
    data["rerank"] = {**data["rerank"], "api_key_env": "X"}
    with pytest.raises(ValidationError, match="api_key_env"):
        _parse(data)


def test_request_body_is_native_chat_with_catalogue_and_generation_options() -> None:
    data = _data()
    data["generation"] = {"temperature": 0.7, "seed": 7, "max_tokens": 300}
    data["max_tokens"] = 300
    cfg = _parse(data)
    body = build_ollama_request(build_prompt("Frage?", [hit("gii-bgb-622#0")], cfg), cfg)
    assert body["model"] == "qwen3.8:27b-q8_0"
    assert body["think"] is False
    assert body["stream"] is False
    assert "keep_alive" not in body
    assert body["options"] == {
        "num_ctx": 8192,
        "top_p": 1.0,
        "temperature": 0.7,
        "seed": 7,
        "num_predict": 300,
    }


CHAT = {
    "model": "qwen3.8:27b-q8_0",
    "message": {"role": "assistant", "content": "Die Frist steht in § 622 BGB."},
    "prompt_eval_count": 40,
    "eval_count": 9,
}


@respx.mock
async def test_generator_posts_to_api_chat_never_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_CANDIDATE_API_KEY", "k1")
    cfg = load_config(GPU, catalogue_path=CATALOGUE)
    route = respx.post("http://llm-proxy:11500/api/chat").mock(
        return_value=httpx.Response(200, json=CHAT)
    )
    out = await OllamaChatGenerator(cfg, "http://llm-proxy:11500", stats=Stats()).answer(
        "Frist?", [hit("gii-bgb-622#0")]
    )
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer k1"
    assert json.loads(request.content)["options"]["num_ctx"] == 8192
    assert out.citations == ["§ 622 BGB"]
    assert (out.prompt_tokens, out.completion_tokens) == (40, 9)


@pytest.mark.parametrize(("name", "field"), sorted(BUG_FIELDS.items()))
def test_every_gpu_bug_config_differs_from_rag_gpu_in_exactly_one_field(
    name: str, field: str
) -> None:
    path = CONFIGS / "bugs" / "gpu" / f"{name}.yaml"
    good = _flat(_data())
    bug = _flat(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert {k for k in good.keys() | bug.keys() if good.get(k) != bug.get(k)} == {field}
    assert config_hash(load_config(path, catalogue_path=CATALOGUE)) != config_hash(
        load_config(GPU, catalogue_path=CATALOGUE)
    )


def test_all_gpu_bug_files_are_listed() -> None:
    assert {p.stem for p in (CONFIGS / "bugs" / "gpu").glob("*.yaml")} == set(BUG_FIELDS)


def test_tier_profiles_have_different_hashes() -> None:
    assert config_hash(load_config(CONFIGS / "rag.yaml")) != config_hash(
        load_config(GPU, catalogue_path=CATALOGUE)
    )


def test_a_gpu_config_must_set_reranker_explicitly() -> None:
    """The default `off` is the M1 bug value: a gpu config that omits it must not load."""
    data = _data()
    del data["reranker"]
    with pytest.raises(ValidationError, match="reranker"):
        _parse(data)
