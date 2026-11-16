"""Parquet input is read in bounded batches (T2.3 review M2) and dates may be date objects (m3)."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from testsupport.rss import PeakRss

from pruefstand.ingest import records_child
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


def spy_batches(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Record (batch_size, decoded nbytes) of every batch ParquetFile.iter_batches yields."""
    seen: list[tuple[int, int]] = []
    real = pq.ParquetFile.iter_batches

    def wrapper(self: pq.ParquetFile, batch_size: int = 65536, **kwargs: Any) -> Iterator[Any]:
        for batch in real(self, batch_size=batch_size, **kwargs):
            seen.append((batch_size, batch.nbytes))
            yield batch

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", wrapper)
    return seen


IN_PROCESS = OldpLimits(max_parquet_memory_bytes=0, max_record_bytes=1 * MIB)  # the spy sees it
BIG = "a" * 2_000_000


def write_bomb(path: Path, table: pa.Table, **options: Any) -> Path:
    path.parent.mkdir(exist_ok=True)
    pq.write_table(table, path, compression="zstd", **options)
    assert path.stat().st_size < 1 * MIB
    return path


def read_bomb(path: Path, monkeypatch: pytest.MonkeyPatch, rows: int) -> list[tuple[int, int]]:
    seen = spy_batches(monkeypatch)
    loader = OldpLoader(IN_PROCESS)
    assert list(loader.load(path.parent)) == []
    assert loader.stats.problems.counts == {"record_too_large": rows}
    return seen


def test_dictionary_bomb_is_read_one_row_per_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many rows share one big dictionary value: the footer counts it once, each row decodes it."""
    table = pa.table({"id": list(range(1, 101)), "content": [BIG] * 100})
    path = write_bomb(tmp_path / "d" / "x.parquet", table)
    assert pq.ParquetFile(path).metadata.row_group(0).column(1).has_dictionary_page
    seen = read_bomb(path, monkeypatch, 100)
    assert {size for size, _ in seen} == {1}  # never 64 rows of 2 MB at once
    assert max(nbytes for _, nbytes in seen) < 4 * MIB


def test_nested_dictionary_column_is_read_one_row_per_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``content.list.element`` is a nested column: it is matched by its top-level name."""
    content = pa.array([[BIG]] * 100, pa.list_(pa.string()))
    table = pa.table({"id": list(range(1, 101)), "content": content})
    path = write_bomb(tmp_path / "d" / "x.parquet", table)
    column = pq.ParquetFile(path).metadata.row_group(0).column(1)
    assert column.path_in_schema != "content"
    assert column.has_dictionary_page
    seen = spy_batches(monkeypatch)
    list(OldpLoader(IN_PROCESS).load(path.parent))
    assert {size for size, _ in seen} == {1}


def test_delta_byte_array_bomb_is_read_one_row_per_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELTA_BYTE_ARRAY stores a repeated value once as prefix; every row decodes in full."""
    table = pa.table({"id": list(range(1, 101)), "content": [BIG] * 100})
    path = write_bomb(
        tmp_path / "d" / "x.parquet",
        table,
        use_dictionary=False,
        column_encoding={"id": "PLAIN", "content": "DELTA_BYTE_ARRAY"},
    )
    column = pq.ParquetFile(path).metadata.row_group(0).column(1)
    assert "DELTA_BYTE_ARRAY" in column.encodings
    assert not column.has_dictionary_page
    seen = read_bomb(path, monkeypatch, 100)
    assert {size for size, _ in seen} == {1}


def test_the_memory_backstop_ends_an_unknown_bomb_with_a_named_problem(tmp_path: Path) -> None:
    """One row that decodes to 300 MB against a 64 MiB reader limit (footer cap raised)."""
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    table = pa.table({"id": [1], "content": ["a" * 300_000_000]})
    pq.write_table(table, path, compression="zstd", use_dictionary=False)
    limits = OldpLimits(
        max_parquet_memory_bytes=64 * MIB, max_group_bytes=4096 * MIB, max_record_bytes=4096 * MIB
    )
    loader = OldpLoader(limits)
    assert list(loader.load(path.parent)) == []
    assert loader.stats.problems.counts == {"memory_limit": 1}
    assert loader.stats.problems.total == 1  # a counted problem: the CLI exits 1


def test_plain_row_groups_keep_the_larger_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    table = pa.table({"id": list(range(1, 501)), "content": [f"text {i}" for i in range(500)]})
    pq.write_table(table, path, use_dictionary=False)
    seen = spy_batches(monkeypatch)
    assert len(list(OldpLoader(OldpLimits(max_parquet_memory_bytes=0)).load(path.parent))) == 500
    assert {size for size, _ in seen} == {64}


def test_row_numbers_stay_aligned_with_the_file_after_a_dropped_row_group(tmp_path: Path) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    ids = [1, 2, 3, 4, 0, 6]  # row 5 has a bad id; the first group (rows 1-3) is too large
    content = [f"{i}" * 5000 for i in range(3)] + ["y"] * 3
    pq.write_table(
        pa.table({"id": ids, "content": content}), path, row_group_size=3, use_dictionary=False
    )
    loader = OldpLoader(OldpLimits(max_group_bytes=10_000))
    assert [d.doc_id for d in loader.load(path.parent)] == ["oldp-4", "oldp-6"]
    sources = [(p.source, p.kind) for p in loader.stats.problems]
    assert sources == [("x.parquet[0]", "row_group_too_large"), ("x.parquet:5", "bad_record")]


def test_row_group_above_the_uncompressed_cap_is_skipped_unread(tmp_path: Path) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    frame = pl.DataFrame({"id": list(range(20)), "content": [f"{i}" * 200_000 for i in range(20)]})
    frame.write_parquet(path, compression="uncompressed")
    loader = OldpLoader(OldpLimits(max_group_bytes=1 * MIB))
    assert list(loader.load(path.parent)) == []
    assert [p.kind for p in loader.stats.problems] == ["row_group_too_large"]


def test_normal_row_groups_are_streamed_in_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    table = pa.table({"id": list(range(1, 201)), "content": ["a" * 100_000] * 200})  # 20 MB
    pq.write_table(table, path, use_dictionary=False)
    seen = spy_batches(monkeypatch)
    problems: list[Problem] = []
    limits = OldpLimits(max_parquet_memory_bytes=0)
    count = sum(1 for _ in iter_rows(path, ("id", "content"), limits, problems))
    assert (count, problems) == (200, [])
    assert {size for size, _ in seen} == {10}  # about 1 MiB of footer size per batch
    assert max(nbytes for _, nbytes in seen) < 2 * MIB  # never the whole 20 MB row group


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


def test_the_reader_ignores_modules_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    pq.write_table(pa.table({"id": [1], "content": ["x"]}), path)
    work = tmp_path / "cwd"
    work.mkdir()
    for name in ("json", "resource", "pickle"):
        (work / f"{name}.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
    monkeypatch.chdir(work)
    loader = OldpLoader()
    assert [d.doc_id for d in loader.load(path.parent)] == ["oldp-1"]
    assert loader.stats.problems.total == 0


class FakeResource:
    """Stands in for the ``resource`` module: records the limit that is set."""

    RLIMIT_AS = 9
    RLIM_INFINITY = -1

    def __init__(self, hard: int) -> None:
        self.hard = hard
        self.set_to: tuple[int, int] | None = None

    def getrlimit(self, _which: int) -> tuple[int, int]:
        return (self.hard, self.hard)

    def setrlimit(self, _which: int, limits: tuple[int, int]) -> None:
        self.set_to = limits

    def getpagesize(self) -> int:
        return 4096


def test_the_memory_limit_is_clamped_to_an_existing_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeResource(hard=3_000_000_000)
    monkeypatch.setattr(records_child, "resource", fake)
    monkeypatch.setattr(records_child, "_virtual_bytes", lambda: 2_900_000_000)
    assert records_child._limit_memory(512 * MIB) is None
    assert fake.set_to == (3_000_000_000, 3_000_000_000)  # not base + 512 MiB: that raises
    unlimited = FakeResource(hard=-1)
    monkeypatch.setattr(records_child, "resource", unlimited)
    assert records_child._limit_memory(512 * MIB) is None
    # soft = hard: the reader cannot raise its own limit again (review F5, D1122)
    assert unlimited.set_to == (2_900_000_000 + 512 * MIB, 2_900_000_000 + 512 * MIB)


def test_a_limit_that_cannot_be_set_is_reported_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(records_child, "_virtual_bytes", lambda: 0)
    assert "unavailable" in str(records_child._limit_memory(512 * MIB))
    assert records_child._limit_memory(0) is None  # in-process reading asked for no limit


@pytest.mark.parametrize("margin", [2, 8, 16])
def test_a_tiny_limit_is_a_memory_limit_problem_not_a_bad_file(tmp_path: Path, margin: int) -> None:
    """The reader may not even start a worker thread: that is the limit, not a corrupt file."""
    path = tmp_path / "d" / "x.parquet"
    path.parent.mkdir()
    pq.write_table(pa.table({"id": [1], "content": ["x"]}), path)
    loader = OldpLoader(OldpLimits(max_parquet_memory_bytes=margin * MIB))
    docs = list(loader.load(path.parent))
    assert len(docs) + loader.stats.problems.counts.get("memory_limit", 0) == 1
    assert "bad_file" not in loader.stats.problems.counts


def test_a_corrupt_parquet_file_is_still_a_bad_file(tmp_path: Path) -> None:
    (tmp_path / "x.parquet").write_bytes(b"PAR1 this is not parquet PAR1")
    loader = OldpLoader()
    assert list(loader.load(tmp_path)) == []
    assert loader.stats.problems.counts == {"bad_file": 1}
