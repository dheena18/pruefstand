"""Indexer choreography against Qdrant's REST API (respx records the calls) and pure builders."""

import json
import uuid
from typing import Any

import httpx
import pytest
import respx
from rd_support import CONFIGS, FIXTURE_CORPUS

from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.errors import IndexMismatchError, RetrievalError
from rag_demo.index.corpus_reader import read_corpus
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.indexer import Indexer, IndexTarget, alias_actions, build_point
from rag_demo.index.naming import ALIAS, analyzer_hash, collection_name, slug
from rag_demo.index.qdrant_admin import QdrantAdmin
from rag_demo.wiring import build_analyzer

QDRANT = "http://qdrant.test:6333"
TEI = "http://embed.test:8090"
CFG = load_config(CONFIGS / "rag.yaml")
MANIFEST, ROWS = read_corpus(FIXTURE_CORPUS)
Call = tuple[str, str, dict[str, Any]]


# --- naming ---------------------------------------------------------------------------------


def test_slug_keeps_letters_digits_and_dashes() -> None:
    assert slug("intfloat/multilingual-e5-small") == "intfloat-multilingual-e5-small"
    assert slug("bge-m3") == "bge-m3"
    assert slug("slice-2026-10-31.51fd4b94") == "slice-2026-10-31-51fd4b94"


def test_collection_name_is_the_index_fingerprint() -> None:
    name = collection_name("2026-11-03.abcd1234", "0123abcd", "BAAI/bge-m3")
    assert name == "chunks__2026-11-03-abcd1234__0123abcd__baai-bge-m3"


def test_analyzer_hash_changes_with_compound_split() -> None:
    on = analyzer_hash(build_analyzer(CFG), SparseEncoder())
    flipped = CFG.analyzer.model_copy(update={"compound_split": False})
    off = analyzer_hash(
        build_analyzer(CFG.model_copy(update={"analyzer": flipped})), SparseEncoder()
    )
    assert len(on) == 8
    assert on != off
    assert on == analyzer_hash(build_analyzer(CFG), SparseEncoder())  # stable


# --- pure builders --------------------------------------------------------------------------


def test_alias_actions_switch_in_one_atomic_request() -> None:
    assert alias_actions(ALIAS, "a", "b") == [
        {"delete_alias": {"alias_name": ALIAS}},
        {"create_alias": {"collection_name": "b", "alias_name": ALIAS}},
    ]
    assert alias_actions(ALIAS, None, "b") == [
        {"create_alias": {"collection_name": "b", "alias_name": ALIAS}}
    ]


def test_point_has_uuid5_id_named_vectors_and_the_full_payload() -> None:
    row = ROWS[0]
    point = build_point(row, [0.5, 0.5], SparseEncoder().encode(["frist"]))
    namespace = uuid.UUID("6f1a8f64-3c1e-4b0e-9d52-5f0b7b1c2a10")
    assert point["id"] == str(uuid.uuid5(namespace, row["chunk_id"]))
    assert set(point["vector"]) == {"dense", "sparse"}
    assert point["payload"] == {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "tenant_id": row["tenant"],
        "citation_key": row["citation_key"],
        "section": row["section"],
        "lang": row["lang"],
        "text": row["text"],
        "source": row["source"],
        "is_attack": row["is_attack"],
        "version_date": row["version_date"],
    }


# --- the flow -------------------------------------------------------------------------------


def _mock_qdrant(
    *, existing: dict[str, Any] | None = None, alias_to: str | None = None
) -> list[Call]:
    """Answer Qdrant calls with canned success bodies and record (method, path, body)."""
    calls: list[Call] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        calls.append((request.method, path, body))
        if request.method == "GET" and path == "/aliases":
            aliases = [{"alias_name": ALIAS, "collection_name": alias_to}] if alias_to else []
            return httpx.Response(200, json={"result": {"aliases": aliases}})
        if request.method == "GET" and path.startswith("/collections/"):
            if existing is None:
                return httpx.Response(404, json={"status": {"error": "not found"}})
            return httpx.Response(200, json={"result": existing})
        return httpx.Response(200, json={"result": True})

    respx.route(host="qdrant.test").mock(side_effect=handler)
    return calls


def _tei() -> None:
    respx.post(f"{TEI}/embed").mock(
        side_effect=lambda req: httpx.Response(
            200, json=[[0.6, 0.8]] * len(json.loads(req.content)["inputs"])
        )
    )


def _indexer(collection: str | None = None, alias: str | None = ALIAS) -> Indexer:
    cfg = CFG.model_copy(update={"embed": CFG.embed.model_copy(update={"dim": 2})})
    return Indexer(
        QDRANT,
        TeiDenseEncoder(cfg.embed, TEI),
        build_analyzer(cfg),
        SparseEncoder(),
        target=IndexTarget(cfg.embed.model, collection=collection, alias=alias),
    )


@respx.mock
def test_new_collection_is_built_fully_before_the_alias_switches() -> None:
    calls = _mock_qdrant()
    _tei()
    indexer = _indexer()
    indexer.index(FIXTURE_CORPUS)
    report = indexer.last_report
    assert report is not None
    assert report.chunks == 40
    assert report.collection.startswith("chunks__fixture-2026-11-03-")
    assert report.alias == ALIAS
    assert report.alias_switched is True
    steps = [(m, p.rsplit("/", 1)[-1]) for m, p, _ in calls if m != "GET"]
    assert steps[0] == ("PUT", report.collection)  # create
    assert steps[-1] == ("POST", "aliases")  # last: the switch
    assert steps.count(("PUT", "points")) == 2  # 40 chunks, batches of 32
    create = next(b for m, p, b in calls if m == "PUT" and p.endswith(report.collection))
    assert create["vectors"] == {"dense": {"size": 2, "distance": "Cosine"}}
    assert create["sparse_vectors"] == {"sparse": {"modifier": "idf"}}
    assert create["metadata"]["corpus_version"] == MANIFEST["corpus_version"]
    assert create["metadata"]["analyzer"] == fingerprint(build_analyzer(CFG), SparseEncoder())
    assert create["metadata"]["avgdl"] > 0


@respx.mock
def test_payload_indexes_tenant_is_tenant_and_the_filter_fields() -> None:
    calls = _mock_qdrant()
    _tei()
    _indexer().index(FIXTURE_CORPUS)
    schemas = {b["field_name"]: b["field_schema"] for _, p, b in calls if p.endswith("/index")}
    assert schemas["tenant_id"] == {"type": "keyword", "is_tenant": True}
    assert schemas["lang"] == "keyword"
    assert schemas["doc_id"] == "keyword"
    assert schemas["is_attack"] == "bool"


@respx.mock
def test_pr_collection_without_alias_never_touches_aliases() -> None:
    calls = _mock_qdrant()
    _tei()
    indexer = _indexer(collection="pr_7_abc1234", alias=None)
    indexer.index(FIXTURE_CORPUS)
    assert indexer.last_report is not None
    assert indexer.last_report.collection == "pr_7_abc1234"
    assert indexer.last_report.alias_switched is False
    assert not any("aliases" in p for _, p, _ in calls)


@respx.mock
def test_rerun_upserts_prunes_stale_points_and_does_not_recreate() -> None:
    existing = {"config": {"params": {"vectors": {"dense": {"size": 2}}}}, "points_count": 40}
    name = "pr_9_x"
    calls = _mock_qdrant(existing=existing, alias_to=name)
    _tei()
    _indexer(collection=name).index(FIXTURE_CORPUS)
    puts = [p.rsplit("/", 1)[-1] for m, p, _ in calls if m == "PUT"]
    assert name not in puts  # the collection is not created again
    prune = next(b for _, p, b in calls if p.endswith("/points/delete"))
    assert len(prune["filter"]["must_not"][0]["has_id"]) == 40
    patch = next(b for m, _, b in calls if m == "PATCH")
    assert patch["metadata"]["truncated_chunks"] == 0


@respx.mock
def test_existing_collection_with_another_dimension_is_refused() -> None:
    existing = {"config": {"params": {"vectors": {"dense": {"size": 384}}}}}
    _mock_qdrant(existing=existing)
    _tei()
    with pytest.raises(IndexMismatchError, match="384"):
        _indexer(collection="slice_v2").index(FIXTURE_CORPUS)


@respx.mock
def test_qdrant_error_is_a_retrieval_error_without_the_api_key() -> None:
    respx.route(host="qdrant.test").mock(return_value=httpx.Response(401, text="key secret-key"))
    admin = QdrantAdmin(QDRANT, api_key="secret-key")
    with pytest.raises(RetrievalError) as err:
        admin.alias_target(ALIAS)
    assert "secret-key" not in str(err.value)
    assert "401" in str(err.value)


@respx.mock
def test_api_key_is_sent_as_api_key_header() -> None:
    route = respx.route(host="qdrant.test").mock(
        return_value=httpx.Response(200, json={"result": {"aliases": []}})
    )
    QdrantAdmin(QDRANT, api_key="k9").alias_target(ALIAS)
    assert route.calls.last.request.headers["api-key"] == "k9"


@respx.mock
def test_unreachable_qdrant_is_a_retrieval_error() -> None:
    respx.route(host="qdrant.test").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(RetrievalError, match="unreachable"):
        QdrantAdmin(QDRANT).alias_target(ALIAS)


@respx.mock
def test_drop_deletes_a_pr_collection_but_refuses_the_active_one() -> None:
    calls = _mock_qdrant(alias_to="chunks__v__h__m")
    admin = QdrantAdmin(QDRANT)
    admin.drop("pr_7_abc1234", alias=ALIAS)
    assert ("DELETE", "/collections/pr_7_abc1234") in [(m, p) for m, p, _ in calls]
    with pytest.raises(RetrievalError, match="active"):
        admin.drop("chunks__v__h__m", alias=ALIAS)
