"""Corpus reader, point ids and the small config helpers (real slice files)."""

import json
import shutil
from pathlib import Path

import pytest
from rd_support import CONFIGS, REPO, SLICE

from rag_demo.config import Settings, parse_config, prompt_path
from rag_demo.errors import ConfigError, CorpusError
from rag_demo.index import index_text, point_id, read_corpus


def test_slice_reads_and_validates() -> None:
    manifest, rows = read_corpus(SLICE)
    assert len(rows) == sum(manifest["tenants"].values())
    assert {r["tenant"] for r in rows} == set(manifest["tenants"])


def _copy_slice(tmp_path: Path) -> Path:
    target = tmp_path / "corpus" / "slice_v1"
    shutil.copytree(SLICE, target)
    shutil.copytree(REPO / "schemas", tmp_path / "schemas")
    return target


def test_a_row_that_violates_the_schema_is_rejected(tmp_path: Path) -> None:
    corpus = _copy_slice(tmp_path)
    path = corpus / "versicherung_nord.chunks.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    del rows[0]["license"]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    with pytest.raises(CorpusError, match=r"versicherung_nord\.chunks\.jsonl:1"):
        read_corpus(corpus)


def test_missing_manifest_is_a_corpus_error(tmp_path: Path) -> None:
    corpus = _copy_slice(tmp_path)
    (corpus / "manifest.json").unlink()
    with pytest.raises(CorpusError, match="cannot read corpus metadata"):
        read_corpus(corpus)


def test_point_ids_are_stable_uuids() -> None:
    assert point_id("gii-bgb-622#1") == point_id("gii-bgb-622#1")
    assert point_id("gii-bgb-622#1") != point_id("gii-bgb-622#2")
    assert len(point_id("x")) == 36


def test_index_text_puts_the_citation_key_first() -> None:
    assert index_text({"citation_key": "§ 622 BGB", "text": "Frist"}) == "§ 622 BGB\nFrist"
    assert index_text({"citation_key": None, "text": "Frist"}) == "Frist"


def test_prompt_path_stays_inside_the_package() -> None:
    with pytest.raises(ConfigError):
        prompt_path("../config.py")
    with pytest.raises(ConfigError):
        prompt_path("prompts/does_not_exist.txt")


def test_config_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError):
        parse_config("- a\n- b\n")


def test_reranker_on_is_rejected_until_t3_5() -> None:
    text = (
        (CONFIGS / "rag.yaml")
        .read_text(encoding="utf-8")
        .replace('reranker: "off"', 'reranker: "on"')
    )
    with pytest.raises(ValueError, match=r"T3\.5"):
        parse_config(text)


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_COLLECTION", "other")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    settings = Settings()
    assert settings.collection == "other"
    assert settings.qdrant_url == "http://qdrant:6333"
