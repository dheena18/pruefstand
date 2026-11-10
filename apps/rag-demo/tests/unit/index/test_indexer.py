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
from rag_demo.errors import EncoderError, RetrievalError
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


class Qdrant:
    """Canned Qdrant answers with the little state a build needs; records (method, path, body)."""

    def __init__(self, existing: set[str] | None = None, alias_to: str | None = None) -> None:
        self.existing = set(existing or ())
        self.alias_to = alias_to
        self.calls: list[Call] = []
        respx.route(host="qdrant.test").mock(side_effect=self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.calls.append((request.method, path, body))
        if request.method == "GET" and path == "/aliases":
            aliases = [{"alias_name": ALIAS, "collection_name": self.alias_to}]
            return httpx.Response(
                200, json={"result": {"aliases": aliases if self.alias_to else []}}
            )
        name = path.split("/")[2] if path.startswith("/collections/") else ""
        if request.method == "GET":
            if name not in self.existing:
                return httpx.Response(404, json={"status": {"error": "not found"}})
            return httpx.Response(200, json={"result": {}})
        if request.method == "PUT" and path == f"/collections/{name}":
            self.existing.add(name)
        if request.method == "DELETE":
            self.existing.discard(name)
        if request.method == "POST" and path == "/collections/aliases":
            self.alias_to = body["actions"][-1]["create_alias"]["collection_name"]
        return httpx.Response(200, json={"result": True})

    def steps(self) -> list[tuple[str, str]]:
        """Non-GET calls as (method, last path segment)."""
        return [(m, p.rsplit("/", 1)[-1]) for m, p, _ in self.calls if m != "GET"]


def _tei(fail_on_call: int | None = None) -> None:
    calls = {"n": 0}

    def reply(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            return httpx.Response(400)
        return httpx.Response(200, json=[[0.6, 0.8]] * len(json.loads(req.content)["inputs"]))

    respx.post(f"{TEI}/embed").mock(side_effect=reply)


def _indexer(collection: str | None = None, alias: str | None = ALIAS) -> Indexer:
    cfg = CFG.model_copy(update={"embed": CFG.embed.model_copy(update={"dim": 2})})
    return Indexer(
        QDRANT,
        TeiDenseEncoder(cfg.embed, TEI, sleep=lambda _s: None),
        build_analyzer(cfg),
        SparseEncoder(),
        target=IndexTarget(cfg.embed.model, collection=collection, alias=alias, build_id="1"),
    )


@respx.mock
def test_every_build_goes_into_a_fresh_collection_and_the_alias_switches_last() -> None:
    qdrant = Qdrant()
    _tei()
    indexer = _indexer()
    indexer.index(FIXTURE_CORPUS)
    report = indexer.last_report
    assert report is not None
    assert report.chunks == 45
    assert report.collection.startswith("chunks__fixture-2026-11-03-")
    assert report.collection.endswith("__b1")
    assert report.alias_switched is True
    steps = qdrant.steps()
    assert steps[0] == ("PUT", report.collection)  # create
    assert steps[-1] == ("POST", "aliases")  # last: the switch
    assert steps.count(("PUT", "points")) == 2  # 45 chunks, batches of 32
    create = next(b for m, p, b in qdrant.calls if m == "PUT" and p.endswith(report.collection))
    assert create["vectors"] == {"dense": {"size": 2, "distance": "Cosine"}}
    assert create["sparse_vectors"] == {"sparse": {"modifier": "idf"}}
    assert create["metadata"]["corpus_version"] == MANIFEST["corpus_version"]
    assert create["metadata"]["analyzer"] == fingerprint(build_analyzer(CFG), SparseEncoder())
    assert create["metadata"]["avgdl"] > 0
    assert create["metadata"]["complete"] is False  # a half-built collection is never servable
    final = [b for m, _, b in qdrant.calls if m == "PATCH"][-1]
    assert final["metadata"]["complete"] is True
    assert steps.index(("PATCH", report.collection)) > max(
        i for i, s in enumerate(steps) if s == ("PUT", "points")
    )


@respx.mock
def test_the_old_collection_is_deleted_only_after_the_alias_swap() -> None:
    qdrant = Qdrant(existing={"chunks__old"}, alias_to="chunks__old")
    _tei()
    indexer = _indexer()
    indexer.index(FIXTURE_CORPUS)
    steps = qdrant.steps()
    assert steps.index(("POST", "aliases")) < steps.index(("DELETE", "chunks__old"))
    assert qdrant.alias_to == indexer.last_report.collection  # type: ignore[union-attr]
    assert qdrant.existing == {indexer.last_report.collection}  # type: ignore[union-attr]


@respx.mock
def test_a_build_that_fails_midway_leaves_the_served_alias_on_the_old_collection() -> None:
    qdrant = Qdrant(existing={"chunks__old"}, alias_to="chunks__old")
    _tei(fail_on_call=3)  # dim probe, first batch ok, second batch fails
    with pytest.raises(EncoderError):
        _indexer().index(FIXTURE_CORPUS)
    assert ("POST", "aliases") not in qdrant.steps()
    assert qdrant.alias_to == "chunks__old"
    assert "chunks__old" in qdrant.existing
    assert len(qdrant.existing) == 1  # the partial collection was dropped again


@respx.mock
def test_payload_indexes_tenant_is_tenant_and_the_filter_fields() -> None:
    qdrant = Qdrant()
    _tei()
    _indexer().index(FIXTURE_CORPUS)
    schemas = {
        b["field_name"]: b["field_schema"] for _, p, b in qdrant.calls if p.endswith("/index")
    }
    assert schemas["tenant_id"] == {"type": "keyword", "is_tenant": True}
    assert schemas["lang"] == "keyword"
    assert schemas["doc_id"] == "keyword"
    assert schemas["is_attack"] == "bool"


@respx.mock
def test_pr_collection_without_alias_never_touches_aliases() -> None:
    qdrant = Qdrant()
    _tei()
    indexer = _indexer(collection="pr_7_abc1234", alias=None)
    indexer.index(FIXTURE_CORPUS)
    assert indexer.last_report is not None
    assert indexer.last_report.collection == "pr_7_abc1234"
    assert indexer.last_report.alias_switched is False
    assert not any("aliases" in p for _, p, _ in qdrant.calls)


@respx.mock
def test_an_existing_pr_collection_is_dropped_and_rebuilt() -> None:
    qdrant = Qdrant(existing={"pr_9_x"})
    _tei()
    _indexer(collection="pr_9_x", alias=None).index(FIXTURE_CORPUS)
    steps = qdrant.steps()
    assert steps[:2] == [("DELETE", "pr_9_x"), ("PUT", "pr_9_x")]


@respx.mock
def test_an_explicit_name_that_is_the_served_collection_is_refused() -> None:
    qdrant = Qdrant(existing={"chunks__live"}, alias_to="chunks__live")
    _tei()
    with pytest.raises(RetrievalError, match="active"):
        _indexer(collection="chunks__live").index(FIXTURE_CORPUS)
    assert qdrant.steps() == []


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
    qdrant = Qdrant(alias_to="chunks__v__h__m")
    admin = QdrantAdmin(QDRANT)
    admin.drop("pr_7_abc1234", alias=ALIAS)
    assert ("DELETE", "/collections/pr_7_abc1234") in [(m, p) for m, p, _ in qdrant.calls]
    with pytest.raises(RetrievalError, match="active"):
        admin.drop("chunks__v__h__m", alias=ALIAS)
