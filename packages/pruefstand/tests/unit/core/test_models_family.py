import re
from importlib.resources import files
from typing import Any

import pytest
import yaml

from pruefstand.core.models_family import known_families, model_family


def table() -> dict[str, Any]:
    text = files("pruefstand.core.data").joinpath("model_families.yaml").read_text("utf-8")
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    return parsed


@pytest.mark.parametrize(
    ("model_id", "family"),
    [
        ("ollama/qwen3:14b", "qwen"),
        ("github/mistral-ai/mistral-small-2503", "mistral"),
        ("github/meta/llama-3.3-70b-instruct", "llama"),
        ("github/openai/gpt-4.1", "gpt"),
        ("github/openai/o4-mini", "gpt"),
        ("github/openai/gpt-oss-20b", "gpt"),
        ("openai_compatible_local/qwen2.5-0.5b-instruct", "qwen"),
        ("ollama/qwen3.8:27b-q8_0", "qwen"),
        ("ollama/qwen35", "qwen"),
        ("ollama/gemma3:12b", "gemma"),
        ("ollama/gemma3:4b", "gemma"),
        ("ollama/bge-m3", "bge"),
        ("foo/bar", "unknown"),
        ("OLLAMA/GEMMA3:12B", "gemma"),
        ("gemini/gemma-3-27b-it", "gemma"),
        ("openrouter/deepseek/deepseek-chat:free", "deepseek"),
        ("groq/llama-3.1-8b-instant", "llama"),
        ("mistral/ministral-8b-latest", "mistral"),
        ("ollama/phi4", "phi"),
        ("ollama/command-r", "command"),
        ("ollama/claude-3", "claude"),
    ],
)
def test_model_family(model_id: str, family: str) -> None:
    assert model_family(model_id) == family


def test_only_one_provider_prefix_is_stripped() -> None:
    # "ollama/" is stripped once; the remaining "github/..." text is matched as is.
    assert model_family("ollama/github/qwen3") == "qwen"
    assert model_family("") == "unknown"


def test_every_row_family_is_known() -> None:
    data = table()
    assert {row["family"] for row in data["patterns"]} <= known_families()
    assert "unknown" not in known_families()


def test_every_pattern_compiles() -> None:
    data = table()
    assert data["patterns"]
    for row in data["patterns"]:
        assert set(row) == {"pattern", "family"}
        re.compile(row["pattern"])
    assert all(isinstance(p, str) and p.endswith("/") for p in data["provider_prefixes"])


def test_known_families_is_frozen_and_cached() -> None:
    first = known_families()
    assert isinstance(first, frozenset)
    assert known_families() is first
    assert {"qwen", "gemma", "gpt", "mistral", "llama"} <= first
