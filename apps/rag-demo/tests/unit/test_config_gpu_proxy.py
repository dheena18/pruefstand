"""D1081: every tier-2 rag-demo profile reaches its models only through LLM_PROXY_URL."""

from pathlib import Path

import pytest
from rd_support import CONFIGS, REPO

from rag_demo.config import load_config

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
GPU = CONFIGS / "rag.gpu.yaml"


@pytest.mark.parametrize(
    "path", [GPU, *sorted((CONFIGS / "bugs" / "gpu").glob("*.yaml"))], ids=lambda p: p.name
)
def test_every_tier2_profile_reaches_models_only_through_llm_proxy(path: Path) -> None:
    # D1081 (closes the D1068 open point): the candidate gets LLM_PROXY_URL, never OLLAMA_GPU*_URL
    text = path.read_text(encoding="utf-8")
    assert "OLLAMA_GPU" not in text
    cfg = load_config(path, catalogue_path=CATALOGUE)
    assert cfg.generator.endpoint_env == "LLM_PROXY_URL"
    assert cfg.embed.endpoint_env == "LLM_PROXY_URL"
