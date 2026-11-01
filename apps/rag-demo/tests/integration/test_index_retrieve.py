"""Indexer + Retriever against real Qdrant and real TEI (Testcontainers)."""

import json

import httpx
import pytest
from conftest import SLICE

pytestmark = pytest.mark.integration
MANIFEST = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))


def test_collection_holds_every_chunk_with_a_tenant_payload_index(qdrant_url: str) -> None:
    info = httpx.get(f"{qdrant_url}/collections/slice_v1", timeout=10).json()["result"]
    assert info["points_count"] == sum(MANIFEST["tenants"].values())
    assert "tenant_id" in info["payload_schema"]
    assert info["config"]["metadata"]["corpus_version"] == MANIFEST["corpus_version"]


def test_kuendigungsfrist_question_finds_paragraph_622(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever()
    hits = retriever.retrieve(
        "kanzlei_mueller", "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?", 4
    )
    assert [h.rank for h in hits] == [1, 2, 3, 4]
    assert any(h.chunk_id == "gii-bgb-622#0" for h in hits)
    assert {h.tenant_id for h in hits} <= {"kanzlei_mueller", "shared_public"}


def test_reindexing_is_idempotent(qdrant_url: str, make_retriever) -> None:  # type: ignore[no-untyped-def]
    before = httpx.get(f"{qdrant_url}/collections/slice_v1", timeout=10).json()["result"]
    assert before["points_count"] > 0
