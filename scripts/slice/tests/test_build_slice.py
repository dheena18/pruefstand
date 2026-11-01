"""Tests for the slice corpus builder (T1.13 S1): committed corpus and rebuild determinism."""

import json
import re
from pathlib import Path

import pytest
from slice.build_slice import build_slice
from slice.eurlex_min import parse_articles

ROOT = Path(__file__).resolve().parents[3]
SLICE = ROOT / "corpus" / "slice_v1"
RAW = ROOT / "data" / "raw"


def _chunks(tenant: str) -> list[dict[str, object]]:
    path = SLICE / f"{tenant}.chunks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _all_chunks() -> list[dict[str, object]]:
    return [c for p in sorted(SLICE.glob("*.chunks.jsonl")) for c in _chunks(p.name.split(".")[0])]


def test_bgb_622_is_one_chunk_with_its_citation_key() -> None:
    chunk = next(c for c in _chunks("shared_public") if c["chunk_id"] == "gii-bgb-622#0")
    assert chunk["citation_key"] == "§ 622 BGB"
    assert chunk["tenant"] == "shared_public"


def test_dsgvo_article_6_exists_in_de_and_en_with_the_same_parallel_id() -> None:
    rows = [c for c in _chunks("stadtwerke_sued") if c["citation_key"] == "Art. 6 DSGVO"]
    assert {c["lang"] for c in rows} == {"de", "en"}
    assert {c["parallel_id"] for c in rows} == {"32016R0679:art-6"}


def test_every_tenant_and_the_manifest_are_there() -> None:
    manifest = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"slice-\d{4}-\d{2}-\d{2}\.[0-9a-f]{8}", manifest["corpus_version"])
    assert set(manifest["tenants"]) == {
        "kanzlei_mueller",
        "stadtwerke_sued",
        "shared_public",
        "versicherung_nord",
    }
    assert sum(manifest["tenants"].values()) == len(_all_chunks())


def test_slice_stays_small() -> None:
    total = sum(p.stat().st_size for p in SLICE.iterdir())
    assert total < 300_000


def test_every_canary_occurs_in_exactly_one_tenant_file() -> None:
    registry = json.loads((SLICE / "canaries.public.json").read_text(encoding="utf-8"))
    canaries = registry["canaries"]
    assert {c["tenant"] for c in canaries} == {"kanzlei_mueller", "versicherung_nord"}
    assert {c["kind"] for c in canaries} == {"token", "semantic"}
    for canary in canaries:
        owners = {
            p.name
            for p in SLICE.glob("*.chunks.jsonl")
            if canary["token"] in p.read_text(encoding="utf-8")
        }
        assert owners == {f"{canary['tenant']}.chunks.jsonl"}, canary["token"]


def test_private_tenant_holds_only_private_docs_with_canaries() -> None:
    rows = _chunks("versicherung_nord")
    assert len(rows) == 3
    assert any("CANARY-VN-" in str(c["text"]) for c in rows)
    assert any("Bergmann beträgt 47 Tage" in str(c["text"]) for c in rows)


def test_four_planted_injections_with_markers() -> None:
    attacks = [c for c in _all_chunks() if c["is_attack"]]
    assert len(attacks) == 4
    assert {c["tenant"] for c in attacks} <= {"stadtwerke_sued", "shared_public"}
    markers = [re.search(r"PWNED-[0-9a-f]{4}", str(c["text"])) for c in attacks]
    assert all(markers)


def test_chunks_have_the_schema_fields_only() -> None:
    schema = json.loads((ROOT / "schemas" / "chunk.schema.json").read_text(encoding="utf-8"))
    for chunk in _all_chunks():
        assert set(chunk) <= set(schema["properties"])
        assert set(schema["required"]) <= set(chunk)


EURLEX_SNIPPET = """<html><body><div class="eli-subdivision" id="art_6">
<p class="oj-ti-art">Artikel 6</p><div class="eli-title"><p class="oj-sti-art">Rechtmäßigkeit der
Verarbeitung</p></div><div id="006.001"><p class="oj-normal">(1)   Die Verarbeitung ist nur
rechtmäßig, wenn</p><table><tbody><tr><td><p class="oj-normal">a)</p></td><td><p class="oj-normal">die
betroffene Person ihre Einwilligung gegeben hat;</p></td></tr></tbody></table></div></div>
<div class="eli-subdivision" id="art_7"><p class="oj-ti-art">Artikel 7</p></div></body></html>"""


def test_eurlex_min_parses_title_paragraphs_and_table_items() -> None:
    (article,) = parse_articles(EURLEX_SNIPPET, {6})
    assert article.number == 6
    assert article.title == "Rechtmäßigkeit der Verarbeitung"
    assert article.text.splitlines()[0] == "(1) Die Verarbeitung ist nur rechtmäßig, wenn"
    assert "a) die betroffene Person ihre Einwilligung gegeben hat;" in article.text.splitlines()


@pytest.mark.network
@pytest.mark.skipif(not RAW.is_dir(), reason="needs `make data` (data/raw)")
def test_two_builds_are_byte_identical_and_equal_the_committed_slice(tmp_path: Path) -> None:
    first = build_slice(RAW, tmp_path / "a")
    second = build_slice(RAW, tmp_path / "b")
    assert first == second
    for name in sorted(p.name for p in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
        assert (tmp_path / "a" / name).read_bytes() == (SLICE / name).read_bytes()
