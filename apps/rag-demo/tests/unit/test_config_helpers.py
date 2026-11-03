"""Small config helpers: prompt root, config mapping, reranker guard, settings, model sha."""

import pytest
from rd_support import CONFIGS

from rag_demo.config import Settings, parse_config, prompt_path, resolve_model_sha
from rag_demo.errors import ConfigError


def test_prompt_path_stays_inside_the_package() -> None:
    with pytest.raises(ConfigError):
        prompt_path("../config.py")
    with pytest.raises(ConfigError):
        prompt_path("prompts/does_not_exist.txt")


def test_config_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError):
        parse_config("- a\n- b\n")


def test_reranker_on_is_rejected_until_t3_5() -> None:
    text = (
        (CONFIGS / "rag.yaml")
        .read_text(encoding="utf-8")
        .replace('reranker: "off"', 'reranker: "on"')
    )
    with pytest.raises(ValueError, match=r"T3\.5"):
        parse_config(text)


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_COLLECTION", "other")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    settings = Settings()
    assert settings.collection == "other"
    assert settings.qdrant_url == "http://qdrant:6333"


def test_model_sha_is_only_reported_for_the_served_file() -> None:
    pin = "a.gguf=" + "a" * 64
    assert resolve_model_sha(Settings(model_file="a.gguf", model_pin=pin)) == "a" * 64
    assert resolve_model_sha(Settings(model_file="b.gguf", model_pin=pin)) == "unknown"
    assert (
        resolve_model_sha(Settings(model_file="b.gguf", model_pin=pin, model_sha256="c" * 64))
        == "c" * 64
    )
    assert resolve_model_sha(Settings()) == "unknown"
