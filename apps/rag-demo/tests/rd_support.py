"""Shared test helpers: real slice chunks as Hits (no fakes) and integration helpers."""

import json
from pathlib import Path

from rag_demo.models import Hit

APP_DIR = Path(__file__).resolve().parents[1]
REPO = APP_DIR.parents[1]
CONFIGS = APP_DIR / "configs"
CASSETTES = Path(__file__).resolve().parent / "cassettes"
SLICE = REPO / "corpus" / "slice_v1"


def slice_chunks() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(SLICE.glob("*.chunks.jsonl")):
        rows.extend(json.loads(x) for x in path.read_text(encoding="utf-8").splitlines())
    return rows


def hit(chunk_id: str, rank: int = 1, score: float = 0.5) -> Hit:
    row = next(c for c in slice_chunks() if c["chunk_id"] == chunk_id)
    return Hit(
        chunk_id=str(row["chunk_id"]),
        doc_id=str(row["doc_id"]),
        tenant_id=str(row["tenant"]),
        text=str(row["text"]),
        score=score,
        rank=rank,
        citation_key=str(row["citation_key"]) if row["citation_key"] else None,
        section=str(row["section"]) if row["section"] else None,
    )


def attack_hits() -> list[Hit]:
    rows = [c for c in slice_chunks() if c["is_attack"]]
    return [hit(str(c["chunk_id"]), rank=i + 1) for i, c in enumerate(rows)]


BERGMANN = "Wie lang ist die Kündigungsfrist im Rahmenvertrag mit Firma Bergmann?"


def own_and_public(hits: list[Hit]) -> bool:
    return all(h.tenant_id in {"kanzlei_mueller", "shared_public"} for h in hits)


def prefetch_filters(body: dict[str, object]) -> list[object]:
    prefetch = body["prefetch"]
    assert isinstance(prefetch, list)
    return [p.get("filter") for p in prefetch]
