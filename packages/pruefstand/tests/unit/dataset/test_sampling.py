"""Chunk and pair sampling (T4.2 S2): seeded, stratified, public text only."""

import json
from pathlib import Path

import numpy as np
import pytest
from testsupport.qa_support import REPO, as_chunk, chunk, slice_chunks

from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Chunk
from pruefstand.dataset.sampling import (
    estimate_tokens,
    is_public_text,
    load_chunks,
    load_excluded_doc_ids,
    sample_chunks,
    sample_cross_lingual_pairs,
    sample_multi_hop_pairs,
)

SOURCES = REPO / "experiments" / "model_selection" / "indomain_dev_sources.json"
FILLER = (
    "Das Arbeitsverhältnis kann mit einer Frist von vier Wochen zum Fünfzehnten oder zum Ende "
    "eines Kalendermonats gekündigt werden, wenn keine andere Frist vereinbart ist und der "
    "Arbeitnehmer nicht länger als sechs Monate im Betrieb beschäftigt war. Eine kürzere Frist "
    "darf nur einzelvertraglich vereinbart werden, wenn der Arbeitgeber höchstens zwanzig "
    "Arbeitnehmer beschäftigt."
)


def _synthetic(i: int, tenant: str, source: str = "gii:bgb") -> Chunk:
    base = chunk("gii-bgb-622#1")
    return as_chunk(
        base,
        chunk_id=f"d{i}-{tenant}#0",
        doc_id=f"d{i}-{tenant}",
        tenant=tenant,
        source=source,
        text=FILLER,
        citation_key=f"§ {i} BGB",
    )


def _ids(chunks: list[Chunk]) -> list[str]:
    return [c.chunk_id for c in chunks]


def test_same_seed_gives_the_same_chunks_twice() -> None:
    pool = list(slice_chunks().values())
    a = sample_chunks(pool, 5, np.random.default_rng(7))
    b = sample_chunks(pool, 5, np.random.default_rng(7))
    assert _ids(a) == _ids(b)
    assert a


def test_attack_and_private_chunks_are_never_sampled() -> None:
    pool = list(slice_chunks().values())
    got = sample_chunks(pool, 50, np.random.default_rng(1))
    assert got
    assert not [c for c in got if c.is_attack or c.source.startswith("synthetic")]
    assert not is_public_text(chunk("syn-km-kanzleihandbuch#0"))
    assert not is_public_text(chunk("syn-inj-shared-probezeit-tabelle#0"))
    assert is_public_text(chunk("gii-bgb-622#1"))


def test_chunks_under_40_tokens_are_skipped() -> None:
    short = chunk("gii-bgb-622#0")
    assert estimate_tokens(short.text) < 40
    assert short.chunk_id not in _ids(sample_chunks([short], 5, np.random.default_rng(1)))


def test_three_tenants_ten_each() -> None:
    pool = [_synthetic(i, t) for t in ("a", "b", "c") for i in range(25)]
    got = sample_chunks(pool, 10, np.random.default_rng(3))
    assert sorted({c.tenant for c in got}) == ["a", "b", "c"]
    assert {t: sum(1 for c in got if c.tenant == t) for t in "abc"} == {"a": 10, "b": 10, "c": 10}


def test_tenant_filter_and_one_chunk_per_document() -> None:
    pool = list(slice_chunks().values())
    got = sample_chunks(pool, 50, np.random.default_rng(2), tenants=["kanzlei_mueller"])
    assert {c.tenant for c in got} == {"kanzlei_mueller"}
    assert len({c.doc_id for c in got}) == len(got)


def test_stratified_by_source_inside_a_tenant() -> None:
    pool = [_synthetic(i, "a", "gii:bgb") for i in range(10)]
    pool += [_synthetic(100 + i, "a", "eurlex:32016R0679") for i in range(10)]
    got = sample_chunks(pool, 6, np.random.default_rng(5))
    assert sum(c.source.startswith("gii") for c in got) == 3


def test_excluded_documents_are_dropped() -> None:
    pool = [_synthetic(i, "a") for i in range(8)]
    blocked = frozenset({"d0-a", "d1-a"})
    got = sample_chunks(pool, 8, np.random.default_rng(1), exclude_doc_ids=blocked)
    assert len(got) == 6
    assert not blocked & {c.doc_id for c in got}


def test_indomain_dev_sources_are_the_exclusion_list() -> None:
    ids = load_excluded_doc_ids(SOURCES)
    assert len(ids) == 240
    assert "gii-agg-13" in ids


def test_exclusion_file_problems_are_dataset_errors(tmp_path: Path) -> None:
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    with pytest.raises(DatasetError, match="source_passage_ids"):
        load_excluded_doc_ids(bad)
    with pytest.raises(DatasetError, match="cannot read"):
        load_excluded_doc_ids(tmp_path / "missing.json")


def test_load_chunks_reads_every_tenant_file() -> None:
    got = load_chunks(REPO / "corpus" / "slice_v1")
    assert {c.tenant for c in got} == {
        "kanzlei_mueller",
        "shared_public",
        "stadtwerke_sued",
        "versicherung_nord",
    }
    assert _ids(got) == sorted(_ids(got))


def test_multi_hop_pairs_same_law_neighbours() -> None:
    pool = [chunk(f"gii-bgb-{n}#0") for n in (620, 621, 624, 625, 626)]
    pairs = sample_multi_hop_pairs(pool, 10, np.random.default_rng(4))
    assert pairs
    for a, b in pairs:
        assert a.chunk_id != b.chunk_id
        assert a.tenant == b.tenant
        assert a.citation_key
        assert b.citation_key
        assert a.citation_key.endswith("BGB")
        assert b.citation_key.endswith("BGB")


def test_multi_hop_pairs_use_citation_graph_edges() -> None:
    law = as_chunk(_synthetic(1, "a"), citation_key="§ 622 BGB")
    decision = as_chunk(
        _synthetic(2, "a", "oldp:decisions"),
        doc_id="oldp-77",
        chunk_id="oldp-77#0",
        citation_key=None,
        license="ODbL-1.0",
    )
    other = as_chunk(_synthetic(3, "b", "oldp:decisions"), doc_id="oldp-78", chunk_id="oldp-78#0")
    graph = {"oldp-77": ("§ 622 BGB",), "oldp-78": ("§ 622 BGB",)}
    pairs = sample_multi_hop_pairs([law, decision, other], 5, np.random.default_rng(1), graph=graph)
    assert [(a.chunk_id, b.chunk_id) for a, b in pairs] == [(law.chunk_id, "oldp-77#0")]


def test_multi_hop_pairs_never_reuse_a_chunk_and_are_seeded() -> None:
    pool = [chunk(f"gii-bgb-{n}#0") for n in (620, 621, 624, 625, 626)]
    one = sample_multi_hop_pairs(pool, 10, np.random.default_rng(4))
    two = sample_multi_hop_pairs(pool, 10, np.random.default_rng(4))
    assert [(a.chunk_id, b.chunk_id) for a, b in one] == [(a.chunk_id, b.chunk_id) for a, b in two]
    used = [c.chunk_id for pair in one for c in pair]
    assert len(used) == len(set(used))


def test_cross_lingual_pairs_are_de_and_en_of_one_parallel_id() -> None:
    pairs = sample_cross_lingual_pairs(list(slice_chunks().values()), 10, np.random.default_rng(1))
    assert pairs
    for de, en in pairs:
        assert (de.lang.value, en.lang.value) == ("de", "en")
        assert de.parallel_id == en.parallel_id is not None
        assert de.tenant == en.tenant
