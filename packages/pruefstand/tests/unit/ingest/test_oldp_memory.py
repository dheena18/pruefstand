"""Parquet input is read in bounded batches (T2.3 review M2) and dates may be date objects (m3)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from testsupport.rss import PeakRss

from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.ingest.oldp import OldpLimits, OldpLoader
from pruefstand.ingest.records import OldpDataError, Problem, data_files, iter_rows

MIB = 1024 * 1024


def bomb(path: Path, rows: int = 20, chars: int = 5_000_000) -> Path:
    """A few KB on disk, rows * chars uncompressed: one highly compressible row group."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame({"id": list(range(1, rows + 1)), "content": ["a" * chars] * rows})
    frame.write_parquet(path, compression="zstd")
    return path


def test_dictionary_bomb_is_refused_row_by_row(tmp_path: Path) -> None:
    """Twelve 20M-character cells in a few KB: the footer says 20 MB, decoding gives 240 MB."""
    path = bomb(tmp_path / "d" / "x.parquet", rows=12, chars=20_000_000)
    assert path.stat().st_size < 1 * MIB
    loader = OldpLoader()
    with PeakRss() as rss:
        docs = list(loader.load(path.parent))
    assert docs == []
    assert [p.kind for p in loader.stats.problems] == ["record_too_large"] * 12
    assert rss.grown_kib < 150 * 1024  # one row at a time, never all twelve


def test_row_group_above_the_uncompressed_cap_is_skipped_unread(tmp_path: Path) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    frame = pl.DataFrame({"id": list(range(20)), "content": [f"{i}" * 200_000 for i in range(20)]})
    frame.write_parquet(path, compression="uncompressed")
    loader = OldpLoader(OldpLimits(max_group_bytes=1 * MIB))
    assert list(loader.load(path.parent)) == []
    assert [p.kind for p in loader.stats.problems] == ["row_group_too_large"]


def test_normal_row_groups_are_streamed_in_batches(tmp_path: Path) -> None:
    path = bomb(tmp_path / "d" / "x.parquet", rows=200, chars=100_000)  # 20 MB uncompressed
    problems: list[Problem] = []
    with PeakRss() as rss:
        count = sum(1 for _ in iter_rows(path, ("id", "content"), OldpLimits(), problems))
    assert (count, problems) == (200, [])
    assert rss.grown_kib < 40 * 1024  # not the whole row group at once


def test_graph_edges_are_bounded_too(tmp_path: Path) -> None:
    decisions = tmp_path / "oldp_decisions"
    decisions.mkdir()
    (decisions / "a.jsonl").write_text('{"id": 1, "slug": "s"}\n', encoding="utf-8")
    graph = tmp_path / "oldp_citation_graph"
    graph.mkdir()
    edges = pl.DataFrame(
        {
            "from_slug": ["s"] * 12,
            "from_type": ["Case"] * 12,
            "to_type": ["Law"] * 12,
            "to_law_book_code": ["a" * 20_000_000] * 12,
            "to_law_section": ["§ 1"] * 12,
        }
    )
    edges.write_parquet(graph / "g.parquet", compression="zstd")
    problems: list[Problem] = []
    with PeakRss() as rss, pytest.raises(OldpDataError, match="no readable"):
        load_citation_graph(graph, problems=problems)
    assert [p.kind for p in problems] == ["record_too_large"] * 12
    assert rss.grown_kib < 150 * 1024


def test_date_objects_in_parquet_make_title_and_version_date(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        {
            "id": [7],
            "slug": ["x"],
            "court": [{"name": "Amtsgericht Köln"}],
            "file_number": ["1 C 1/20"],
            "date": [date(2020, 3, 4)],
            "content": ["<p>Text</p>"],
        }
    )
    target = tmp_path / "d"
    target.mkdir()
    frame.write_parquet(target / "x.parquet")
    (doc,) = OldpLoader().load(target)
    assert doc.title == "Amtsgericht Köln 2020-03-04 1 C 1/20"
    assert doc.version_date == date(2020, 3, 4)
    assert data_files(target)
