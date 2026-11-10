"""The generator tokenizer is baked at image build, taken from the catalogue pin (AI13-05)."""

import re
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from rd_support import APP_DIR, CONFIGS, REPO

from rag_demo.errors import ConfigError
from rag_demo.index.fetch_tokenizer import generator_id, main

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
URL = "https://huggingface.co/Qwen/Qwen3.8-27B/resolve/37561816e66b5b9153b1b64c10968c18c1e6f4a0/tokenizer.json"


def test_the_generator_id_comes_from_the_config_not_from_code() -> None:
    assert generator_id(CONFIGS / "rag.gpu.yaml") == "ollama/qwen3.8:27b-q8_0"
    with pytest.raises(ConfigError, match="catalogue_id"):
        generator_id(CONFIGS / "rag.yaml")  # the tier-1 profile has no catalogue entry


@respx.mock
def test_a_wrong_sha256_fails_the_fetch_and_leaves_no_file(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"{}"))
    out = tmp_path / "generator.json"
    argv = [
        "--catalogue",
        str(CATALOGUE),
        "--config",
        str(CONFIGS / "rag.gpu.yaml"),
        "--out",
        str(out),
    ]
    with pytest.raises(ConfigError, match="differs from the catalogue pin"):
        main(argv)
    assert not out.exists()


def test_the_dockerfile_bakes_the_generator_tokenizer_next_to_the_embedding_one() -> None:
    text = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert (
        "--config apps/rag-demo/configs/rag.gpu.yaml --out /app/tokenizers/generator.json" in text
    )
    assert "RAG_GENERATOR_TOKENIZER=/app/tokenizers/generator.json" in text


def test_the_generator_tokenizer_source_is_pinned_to_a_hugging_face_commit() -> None:
    entry = next(
        m
        for m in yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["models"]
        if m["id"] == generator_id(CONFIGS / "rag.gpu.yaml")
    )
    assert re.fullmatch(
        r"hf:Qwen/Qwen3\.8-27B@[0-9a-f]{40}/tokenizer\.json", entry["tokenizer"]["source"]
    )
