"""Corpus reader (streamed, schema-checked, file:line errors) on the 40-chunk fixture corpus."""

import json
import shutil
from pathlib import Path

import pytest
from rd_support import FIXTURE_CORPUS, REPO

from rag_demo.errors import CorpusError
from rag_demo.index.corpus_reader import (
    index_text,
    iter_chunks,
    point_id,
    read_corpus,
    read_manifest,
)

SCHEMA_COPY = (
    Path(__file__).resolve().parents[3] / "src" / "rag_demo" / "index" / "chunk.schema.json"
)


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, target)
    return target


def test_fixture_corpus_has_40_chunks_in_four_tenants() -> None:
    manifest, rows = read_corpus(FIXTURE_CORPUS)
    assert len(rows) == 40
    assert {r["tenant"] for r in rows} == {
        "kanzlei_mueller",
        "versicherung_nord",
        "shared_public",
        "stadtwerke_sued",
    }
    assert manifest["tenants"] == {
        t: sum(1 for r in rows if r["tenant"] == t) for t in manifest["tenants"]
    }


def test_rows_are_streamed_in_file_then_line_order() -> None:
    first = next(iter(iter_chunks(FIXTURE_CORPUS)))
    assert first["tenant"] == "kanzlei_mueller"  # kanzlei_mueller.chunks.jsonl sorts first


def test_schema_copy_equals_the_repo_schema_byte_for_byte() -> None:
    assert SCHEMA_COPY.read_bytes() == (REPO / "schemas" / "chunk.schema.json").read_bytes()


def test_a_line_missing_tenant_names_file_and_line(tmp_path: Path) -> None:
    corpus = _copy(tmp_path)
    path = corpus / "versicherung_nord.chunks.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    del rows[1]["tenant"]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    with pytest.raises(CorpusError, match=r"versicherung_nord\.chunks\.jsonl:2"):
        read_corpus(corpus)


def test_invalid_json_names_file_and_line(tmp_path: Path) -> None:
    corpus = _copy(tmp_path)
    path = corpus / "shared_public.chunks.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    with pytest.raises(CorpusError, match=r"shared_public\.chunks\.jsonl:15: invalid JSON"):
        read_corpus(corpus)


def test_a_row_in_the_wrong_tenant_file_is_rejected(tmp_path: Path) -> None:
    corpus = _copy(tmp_path)
    src = corpus / "versicherung_nord.chunks.jsonl"
    dst = corpus / "kanzlei_mueller.chunks.jsonl"
    dst.write_text(
        dst.read_text(encoding="utf-8") + src.read_text(encoding="utf-8").splitlines()[0] + "\n",
        "utf-8",
    )
    with pytest.raises(CorpusError, match=r"kanzlei_mueller\.chunks\.jsonl:15: .*tenant"):
        read_corpus(corpus)


def test_missing_manifest_is_a_corpus_error(tmp_path: Path) -> None:
    corpus = _copy(tmp_path)
    (corpus / "manifest.json").unlink()
    with pytest.raises(CorpusError, match="cannot read corpus manifest"):
        read_manifest(corpus)


def test_empty_corpus_dir_is_a_corpus_error(tmp_path: Path) -> None:
    shutil.copy(FIXTURE_CORPUS / "manifest.json", tmp_path / "manifest.json")
    with pytest.raises(CorpusError, match=r"no .*chunks\.jsonl"):
        read_corpus(tmp_path)


def test_point_ids_are_stable_uuids() -> None:
    assert point_id("gii-bgb-622#1") == point_id("gii-bgb-622#1")
    assert point_id("gii-bgb-622#1") != point_id("gii-bgb-622#2")
    assert len(point_id("x")) == 36


def test_index_text_puts_the_citation_key_first() -> None:
    assert index_text({"citation_key": "§ 622 BGB", "text": "Frist"}) == "§ 622 BGB\nFrist"
    assert index_text({"citation_key": None, "text": "Frist"}) == "Frist"
