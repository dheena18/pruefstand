"""T3.4b: the Indexer with ``chunking`` (respx records the Qdrant calls)."""

import respx
from rd_support import CONFIGS, FIXTURE_CORPUS, QDRANT, TEI, Qdrant
from rd_support import tei_replies as _tei

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.index.corpus_reader import read_corpus
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.indexer import Indexer, IndexTarget
from rag_demo.index.naming import ALIAS  # noqa: F401
from rag_demo.models import ChunkingCfg
from rag_demo.wiring import build_analyzer

CFG = load_config(CONFIGS / "rag.yaml")
_MANIFEST, ROWS = read_corpus(FIXTURE_CORPUS)


@respx.mock
def test_fixed_tokens_indexes_pieces_names_and_records_the_chunking() -> None:
    qdrant = Qdrant()
    _tei()
    cfg = CFG.model_copy(update={"embed": CFG.embed.model_copy(update={"dim": 2})})
    chunking = ChunkingCfg(strategy="fixed_tokens", size=64)
    indexer = Indexer(
        QDRANT,
        TeiDenseEncoder(cfg.embed, TEI, sleep=lambda _s: None),
        build_analyzer(cfg),
        SparseEncoder(),
        target=IndexTarget(cfg.embed.model, build_id="1", chunking=chunking),
    )
    indexer.index(FIXTURE_CORPUS)
    report = indexer.last_report
    assert report is not None
    assert report.chunks > len(ROWS)  # long § text became several points
    assert "__ft64__" in report.collection  # another chunking is another collection
    create = next(b for m, p, b in qdrant.calls if m == "PUT" and p.endswith(report.collection))
    assert create["metadata"]["chunking"] == {"strategy": "fixed_tokens", "size": 64}
    points = [
        pt for m, p, b in qdrant.calls if m == "PUT" and p.endswith("/points") for pt in b["points"]
    ]
    ids = {pt["payload"]["chunk_id"] for pt in points}
    assert any("#p1" in i for i in ids)
    keyed = [pt["payload"] for pt in points if pt["payload"]["citation_key"]]
    assert keyed
    assert not any(p["text"].startswith(p["citation_key"]) for p in keyed)
    assert {pt["payload"]["doc_id"] for pt in points} == {
        r["doc_id"] for r in ROWS
    }  # gold ids hold


@respx.mock
def test_the_default_build_records_per_section_and_keeps_the_collection_name() -> None:
    qdrant = Qdrant()
    _tei()
    indexer = _default_indexer()
    indexer.index(FIXTURE_CORPUS)
    report = indexer.last_report
    assert report is not None
    assert "__ft" not in report.collection
    create = next(b for m, p, b in qdrant.calls if m == "PUT" and p.endswith(report.collection))
    assert create["metadata"]["chunking"] == {"strategy": "per_section", "size": None}


def _default_indexer() -> Indexer:
    cfg = CFG.model_copy(update={"embed": CFG.embed.model_copy(update={"dim": 2})})
    return Indexer(
        QDRANT,
        TeiDenseEncoder(cfg.embed, TEI, sleep=lambda _s: None),
        build_analyzer(cfg),
        SparseEncoder(),
        target=IndexTarget(cfg.embed.model, build_id="1"),
    )
