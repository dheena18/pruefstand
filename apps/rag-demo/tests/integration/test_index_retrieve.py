"""Indexer + Retriever against real Qdrant and real TEI (Testcontainers)."""

import json

import httpx
import pytest
import yaml
from rd_support import MODEL_DIR, REPO, SLICE

pytestmark = pytest.mark.integration
MANIFEST = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))


def test_collection_holds_every_chunk_with_a_tenant_payload_index(qdrant_url: str) -> None:
    info = httpx.get(f"{qdrant_url}/collections/slice_v2", timeout=10).json()["result"]
    assert info["points_count"] == sum(MANIFEST["tenants"].values())
    assert "tenant_id" in info["payload_schema"]
    assert info["config"]["metadata"]["corpus_version"] == MANIFEST["corpus_version"]
    assert info["config"]["metadata"]["avgdl"] > 0
    assert info["config"]["metadata"]["analyzer"]["scheme"] == "xxhash64-mod-dim"


def test_kuendigungsfrist_question_finds_paragraph_622(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever()
    hits = retriever.retrieve(
        "kanzlei_mueller", "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?", 4
    )
    assert [h.rank for h in hits] == [1, 2, 3, 4]
    assert any(h.chunk_id.startswith("gii-bgb-622#") for h in hits)
    assert {h.tenant_id for h in hits} <= {"kanzlei_mueller", "shared_public"}


def test_tei_loaded_the_pinned_weights(tei_url: str) -> None:
    """TEI names its cache blob after the SHA-256 of the file it downloaded (`onnx/model.onnx`)."""
    pins = yaml.safe_load((REPO / "infra" / "models" / "live-models.yaml").read_text("utf-8"))
    emb = pins["embeddings"][0]
    blobs = MODEL_DIR / "tei" / "models--intfloat--multilingual-e5-small" / "blobs"
    assert (blobs / emb["weights_sha256"]).exists()
    assert httpx.get(f"{tei_url}/info", timeout=10).json()["model_id"] == emb["repo"]
