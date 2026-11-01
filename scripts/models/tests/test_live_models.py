"""live-models.yaml, rag.yaml and docker-compose.yml name the same pinned models (T1.13 S7)."""

from pathlib import Path

import yaml
from models.fetch import load_models

ROOT = Path(__file__).resolve().parents[3]
PINS = yaml.safe_load((ROOT / "infra" / "models" / "live-models.yaml").read_text(encoding="utf-8"))
RAG_YAML = ROOT / "apps" / "rag-demo" / "configs" / "rag.yaml"
RAG = yaml.safe_load(RAG_YAML.read_text(encoding="utf-8"))
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_generator_pin_loads_through_the_fetch_mechanism() -> None:
    (entry,) = load_models(ROOT / "infra" / "models" / "live-models.yaml")
    assert entry.license == "Apache-2.0"
    assert entry.file.endswith("Q4_K_M.gguf") or entry.file.endswith("q4_k_m.gguf")


def test_rag_yaml_names_the_pinned_generator() -> None:
    (entry,) = load_models(ROOT / "infra" / "models" / "live-models.yaml")
    assert RAG["generator"]["model"] == entry.id
    assert RAG["generator"]["family"] == PINS["generator_family"]
    assert RAG["generator"]["enable_thinking"] is False


def test_rag_yaml_embed_block_equals_the_embedding_pin() -> None:
    (emb,) = PINS["embeddings"]
    assert RAG["embed"]["model"] == emb["repo"]
    for key in ("query_prefix", "doc_prefix", "max_input_tokens", "dim"):
        assert RAG["embed"][key] == emb[key], key


def test_compose_defaults_equal_the_pins() -> None:
    (entry,) = load_models(ROOT / "infra" / "models" / "live-models.yaml")
    (emb,) = PINS["embeddings"]
    assert f"LIVE_LLM_GGUF:-{entry.file}" in COMPOSE
    assert f"LIVE_LLM_SHA256:-{entry.sha256}" in COMPOSE
    assert f"--model-id {emb['repo']}" in COMPOSE
    assert f"--revision {emb['revision']}" in COMPOSE


def test_embedding_pin_has_license_and_weight_hash() -> None:
    (emb,) = PINS["embeddings"]
    assert emb["license"] == "MIT"
    assert len(emb["revision"]) == 40
    assert len(emb["weights_sha256"]) == 64
