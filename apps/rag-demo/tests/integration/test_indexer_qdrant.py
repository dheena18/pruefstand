"""Indexer against a real Qdrant (fresh container per test) and the real TEI CPU service."""

import json
from collections.abc import Iterator

import httpx
import pytest
from rd_support import CONFIGS, FIXTURE_CORPUS, compose_image, wait_http
from testcontainers.core.container import DockerContainer

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.index.corpus_reader import read_corpus
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.indexer import Indexer, IndexTarget
from rag_demo.index.naming import ALIAS
from rag_demo.index.qdrant_admin import QdrantAdmin
from rag_demo.wiring import build_analyzer

pytestmark = pytest.mark.integration
MANIFEST = json.loads((FIXTURE_CORPUS / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def qdrant() -> Iterator[str]:
    """An empty pinned Qdrant of its own, so alias state never leaks between tests."""
    with DockerContainer(compose_image("qdrant")).with_exposed_ports(6333) as container:
        url = f"http://127.0.0.1:{container.get_exposed_port(6333)}"
        wait_http(f"{url}/readyz")
        yield url


def _indexer(
    qdrant: str,
    tei_url: str,
    *,
    collection: str | None = None,
    alias: str | None = ALIAS,
    compound_split: bool = True,
) -> Indexer:
    cfg = load_config(CONFIGS / "rag.yaml")
    analyzer = cfg.analyzer.model_copy(update={"compound_split": compound_split})
    cfg = cfg.model_copy(update={"analyzer": analyzer})
    return Indexer(
        qdrant,
        TeiDenseEncoder(cfg.embed, tei_url),
        build_analyzer(cfg),
        SparseEncoder(),
        target=IndexTarget(cfg.embed.model, collection=collection, alias=alias),
    )


def _info(qdrant: str, name: str) -> dict[str, object]:
    return httpx.get(f"{qdrant}/collections/{name}", timeout=10).json()["result"]  # type: ignore[no-any-return]  # json


def test_fixture_corpus_gives_40_points_a_tenant_index_and_the_alias(
    qdrant: str, tei_url: str
) -> None:
    indexer = _indexer(qdrant, tei_url)
    indexer.index(FIXTURE_CORPUS)
    report = indexer.last_report
    assert report is not None
    info = _info(qdrant, report.collection)
    assert info["points_count"] == 40
    schema = info["payload_schema"]["tenant_id"]  # type: ignore[index]  # json
    assert schema["data_type"] == "keyword"
    assert schema["params"]["is_tenant"] is True
    assert QdrantAdmin(qdrant).alias_target(ALIAS) == report.collection
    assert info["config"]["metadata"]["corpus_version"] == MANIFEST["corpus_version"]  # type: ignore[index]  # json


def test_every_point_carries_the_tenant_of_its_source_file(qdrant: str, tei_url: str) -> None:
    indexer = _indexer(qdrant, tei_url)
    indexer.index(FIXTURE_CORPUS)
    _, rows = read_corpus(FIXTURE_CORPUS)
    expected = {r["chunk_id"]: r["tenant"] for r in rows}
    body = {"limit": 100, "with_payload": True}
    points = httpx.post(
        f"{qdrant}/collections/{ALIAS}/points/scroll", json=body, timeout=30
    ).json()["result"]["points"]
    assert {p["payload"]["chunk_id"]: p["payload"]["tenant_id"] for p in points} == expected


def test_rerun_builds_a_fresh_collection_swaps_the_alias_and_removes_the_old_one(
    qdrant: str, tei_url: str
) -> None:
    first = _indexer(qdrant, tei_url)
    first.index(FIXTURE_CORPUS)
    second = _indexer(qdrant, tei_url)
    second.index(FIXTURE_CORPUS)
    assert first.last_report is not None
    assert second.last_report is not None
    assert second.last_report.collection != first.last_report.collection
    assert _info(qdrant, ALIAS)["points_count"] == 40  # no duplicates
    assert QdrantAdmin(qdrant).alias_target(ALIAS) == second.last_report.collection
    assert QdrantAdmin(qdrant).collection_info(first.last_report.collection) is None


def test_changing_compound_split_builds_a_new_collection_and_switches_the_alias(
    qdrant: str, tei_url: str
) -> None:
    first = _indexer(qdrant, tei_url)
    first.index(FIXTURE_CORPUS)
    split_off = _indexer(qdrant, tei_url, compound_split=False)
    split_off.index(FIXTURE_CORPUS)
    assert first.last_report is not None
    assert split_off.last_report is not None
    assert split_off.last_report.collection != first.last_report.collection
    assert QdrantAdmin(qdrant).alias_target(ALIAS) == split_off.last_report.collection
    assert _info(qdrant, ALIAS)["config"]["metadata"]["complete"] is True  # type: ignore[index]  # json


def test_pr_collection_leaves_the_active_alias_and_can_be_dropped(
    qdrant: str, tei_url: str
) -> None:
    active = _indexer(qdrant, tei_url)
    active.index(FIXTURE_CORPUS)
    assert active.last_report is not None
    _indexer(qdrant, tei_url, collection="pr_7_abc1234", alias=None).index(FIXTURE_CORPUS)
    admin = QdrantAdmin(qdrant)
    assert admin.alias_target(ALIAS) == active.last_report.collection
    assert _info(qdrant, "pr_7_abc1234")["points_count"] == 40
    admin.drop("pr_7_abc1234", alias=ALIAS)
    assert admin.collection_info("pr_7_abc1234") is None


def test_app_info_reports_the_corpus_version_of_the_indexed_collection(
    qdrant: str, tei_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from rag_demo.api import create_app  # noqa: PLC0415
    from rag_demo.config import Settings  # noqa: PLC0415

    _indexer(qdrant, tei_url).index(FIXTURE_CORPUS)
    cfg = load_config(CONFIGS / "rag.yaml")
    settings = Settings(qdrant_url=qdrant, collection=ALIAS, embed_url=tei_url)
    info = TestClient(create_app(cfg, settings=settings)).get("/v1/info")
    assert info.status_code == 200
    assert info.json()["corpus_version"] == MANIFEST["corpus_version"]
