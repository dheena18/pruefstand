"""Shared test helpers: real slice chunks as Hits (no fakes) and integration helpers."""

import json
import os
import time
from pathlib import Path

import httpx
import yaml

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.naming import ALIAS
from rag_demo.models import Hit, RagConfig
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.rerank import IdentityReranker
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.retrieval.store import QdrantStore
from rag_demo.wiring import build_analyzer, expected_fingerprint

APP_DIR = Path(__file__).resolve().parents[1]
REPO = APP_DIR.parents[1]
CONFIGS = APP_DIR / "configs"
CASSETTES = Path(__file__).resolve().parent / "cassettes"
SLICE = REPO / "corpus" / "slice_v1"
MODEL_DIR = Path(os.environ.get("LIVE_MODEL_DIR", Path.home() / ".cache" / "pruefstand" / "models"))


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
    )


def attack_hits() -> list[Hit]:
    rows = [c for c in slice_chunks() if c["is_attack"]]
    return [hit(str(c["chunk_id"]), rank=i + 1) for i, c in enumerate(rows)]


def fixture_rows() -> dict[str, dict[str, object]]:
    """The 40 real chunks of the test corpus by chunk id (``tests/fixtures/corpus``)."""
    rows: dict[str, dict[str, object]] = {}
    for path in sorted(FIXTURE_CORPUS.glob("*.chunks.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[str(row["chunk_id"])] = row
    return rows


def fixture_hit(chunk_id: str, rank: int = 1, score: float = 0.5) -> Hit:
    """A ``Hit`` made from a real chunk of the test corpus."""
    row = fixture_rows()[chunk_id]
    return Hit(
        chunk_id=chunk_id,
        doc_id=str(row["doc_id"]),
        tenant_id=str(row["tenant"]),
        text=str(row["text"]),
        score=score,
        rank=rank,
        citation_key=str(row["citation_key"]) if row["citation_key"] else None,
        section=str(row["section"]) if row.get("section") else None,
        lang=str(row["lang"]),
    )


def qdrant_point(chunk_id: str, score: float) -> dict[str, object]:
    """A Qdrant scored point (as in a query answer) for a real chunk of the test corpus."""
    row = fixture_rows()[chunk_id]
    payload = {
        "chunk_id": chunk_id,
        "doc_id": row["doc_id"],
        "tenant_id": row["tenant"],
        "citation_key": row["citation_key"],
        "section": row.get("section"),
        "lang": row["lang"],
        "text": row["text"],
    }
    return {"id": chunk_id, "score": score, "payload": payload}


RERANK_QUERY = "Kündigungsfrist nach zwei Jahren"
# Rank order of the fused first stage in the recorded rerank exchange: § 622 Abs. 2 is last.
RERANK_ORDER = (
    "gii-bgb-620#0",
    "gii-kschg-1#0",
    "gii-bgb-623#0",
    "gii-bgb-626#0",
    "gii-bgb-624#0",
    "gii-bgb-625#0",
    "gii-kschg-3#0",
    "gii-arbzg-3#0",
    "gii-bgb-621#0",
    "gii-bgb-622#1",
)


def rerank_input() -> list[Hit]:
    """The ten fused hits sent to the reranker in the recorded exchange (real chunk texts)."""
    return [fixture_hit(cid, rank=i, score=0.1) for i, cid in enumerate(RERANK_ORDER, start=1)]


BERGMANN = "Wie lang ist die Kündigungsfrist im Rahmenvertrag mit Firma Bergmann?"


def own_and_public(hits: list[Hit]) -> bool:
    return all(h.tenant_id in {"kanzlei_mueller", "shared_public"} for h in hits)


def prefetch_filters(body: dict[str, object]) -> list[object]:
    prefetch = body["prefetch"]
    assert isinstance(prefetch, list)
    return [p.get("filter") for p in prefetch]


FIXTURE_CORPUS = APP_DIR / "tests" / "fixtures" / "corpus"


def write_word_tokenizer(path: Path) -> Path:
    """Save a real word-level ``tokenizers`` tokenizer (one token per whitespace-separated word)."""
    from tokenizers import Tokenizer, models, pre_tokenizers  # noqa: PLC0415

    tok = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))  # noqa: S106
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.save(str(path))
    return path


def compose_image(service: str) -> str:
    data = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    return str(data["services"][service]["image"])


def wait_http(url: str, timeout_s: float = 240.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=3).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    msg = f"{url} did not become ready"
    raise TimeoutError(msg)


def build_test_retriever(
    cfg: RagConfig,
    qdrant_url: str,
    tei_url: str,
    *,
    api_key: str | None = None,
    guard: bool = True,
    client: httpx.Client | None = None,
) -> QdrantRetriever:
    """A retriever on the alias ``chunks_active`` of a real Qdrant with the real TEI encoder."""
    store = QdrantStore(qdrant_url, ALIAS, api_key=api_key, client=client)
    return QdrantRetriever(
        cfg,
        store=store,
        corpus=CorpusMeta(store, expected_fingerprint(cfg)),
        dense=TeiDenseEncoder(cfg.embed, tei_url),
        analyzer=build_analyzer(cfg),
        sparse=SparseEncoder(),
        reranker=IdentityReranker(),
        guard=guard,
    )
