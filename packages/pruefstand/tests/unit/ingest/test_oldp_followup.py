"""OLDP loader hardening, part 2 (T2.3a): bad rows, bounded details, shared budget, dates."""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pruefstand.core.ids import DocId
from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.ingest.oldp import OldpLimits, OldpLoader, main
from pruefstand.ingest.records import OldpDataError, Problem, ProblemLog

Rec = Callable[[str], dict[str, object]]
Writer = Callable[[Path, Sequence[Mapping[str, object]]], Path]


def write_dates(path: Path, dates: pa.Array) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = len(dates)
    table = pa.table({"id": list(range(1, rows + 1)), "content": ["x"] * rows, "date": dates})
    pq.write_table(table, path)
    return path


def test_out_of_range_parquet_date_is_one_bad_record_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_dates(tmp_path / "a.parquet", pa.array([0, 2**60, 0], pa.timestamp("ms")))
    loader = OldpLoader()
    docs = list(loader.load(tmp_path))
    assert [d.doc_id for d in docs] == ["oldp-1", "oldp-3"]
    (problem,) = loader.stats.problems
    assert (problem.source, problem.kind) == ("a.parquet:2", "bad_record")
    assert main([str(tmp_path)]) == 1  # a counted problem, not an OverflowError traceback
    assert "a.parquet:2: bad_record" in capsys.readouterr().err


def test_parquet_rows_are_numbered_across_batches(tmp_path: Path) -> None:
    ids = [1, 0, *range(3, 301)]  # row 2 has an invalid id; 300 rows span several batches
    pl.DataFrame({"id": ids, "content": ["x"] * 300}).write_parquet(tmp_path / "a.parquet")
    loader = OldpLoader()
    assert len(list(loader.load(tmp_path))) == 299
    assert [(p.source, p.kind) for p in loader.stats.problems] == [("a.parquet:2", "bad_record")]


def test_problem_details_are_bounded_and_ascii() -> None:
    log = ProblemLog()
    log.append(Problem("f" * 5000, "bad_record", "lone surrogate in " + "\ud800ü" * 2_000_000))
    (kept,) = log
    assert len(kept.detail) <= 200
    assert len(kept.source) <= 200
    assert kept.detail.isascii()
    assert kept.detail.startswith("lone surrogate in \\ud800\\xfc")


def test_huge_key_with_a_lone_surrogate_stays_small_in_log_and_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = "k" * 5_000_000
    line = '{"id": 1, "content": "x", "' + key + '": "\\ud800"}\n'
    (tmp_path / "a.jsonl").write_text(line * 4, encoding="utf-8")
    loader = OldpLoader()
    assert list(loader.load(tmp_path)) == []
    assert sum(len(p.detail) for p in loader.stats.problems) < 1000
    assert main([str(tmp_path)]) == 1
    assert len(capsys.readouterr().err) < 2000


def test_row_budget_is_shared_by_all_files_of_a_directory(tmp_path: Path) -> None:
    for name in "abcde":  # 5 files of 60 bad lines: each is below max_rows, together they are not
        (tmp_path / f"{name}.jsonl").write_text("{not json\n" * 60, encoding="utf-8")
    loader = OldpLoader(OldpLimits(max_rows=100))
    assert list(loader.load(tmp_path)) == []
    assert loader.stats.problems.counts == {"bad_json": 100, "too_many_rows": 1}


def test_file_count_is_capped(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    for number in range(5):
        write_jsonl(tmp_path / f"f{number}.jsonl", [{**base, "id": number + 1}])
    loader = OldpLoader(OldpLimits(max_files=3))
    assert [d.doc_id for d in loader.load(tmp_path)] == ["oldp-1", "oldp-2", "oldp-3"]
    assert loader.stats.problems.counts == {"too_many_files": 1}


def test_bad_id_names_the_line(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    write_jsonl(tmp_path / "a.jsonl", [base, {**base, "id": "abc"}])
    loader = OldpLoader()
    assert len(list(loader.load(tmp_path))) == 1
    (problem,) = loader.stats.problems
    assert (problem.source, problem.kind) == ("a.jsonl:2", "bad_record")


def test_reused_problem_log_does_not_turn_an_empty_graph_into_an_error(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    write_jsonl(tmp_path / "oldp_decisions" / "a.jsonl", [oldp_record("labour_lag_hessen")])
    graph = tmp_path / "oldp_citation_graph"
    graph.mkdir()
    (graph / "e.jsonl").write_text("", encoding="utf-8")
    log = ProblemLog()
    log.append(Problem("earlier", "bad_json", "from a previous load"))
    assert load_citation_graph(graph, problems=log) == {}
    (graph / "e.jsonl").write_text("{not json\n", encoding="utf-8")
    with pytest.raises(OldpDataError, match="no readable edge row"):
        load_citation_graph(graph, problems=ProblemLog())


@pytest.mark.parametrize(
    "value", [20200101, float("nan"), "2020-01-01garbage", "1.1.2020", 1.5, True, "2020-13-01"]
)
def test_values_that_are_not_dates_are_counted_bad_dates(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer, value: object
) -> None:
    row = {**oldp_record("labour_lag_hessen"), "date": value}
    (tmp_path / "a.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    loader = OldpLoader()
    (doc,) = loader.load(tmp_path)
    assert doc.version_date is None
    assert [p.kind for p in loader.stats.problems] == ["bad_date"]


@pytest.mark.parametrize("value", ["2020-01-01", "2020-01-01T10:30:00", "2020-01-01T10:30:00Z"])
def test_iso_dates_with_or_without_a_time_are_accepted(
    tmp_path: Path, oldp_record: Rec, value: str
) -> None:
    row = {**oldp_record("labour_lag_hessen"), "date": value}
    (tmp_path / "a.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    loader = OldpLoader()
    (doc,) = loader.load(tmp_path)
    assert str(doc.version_date) == "2020-01-01"
    assert loader.stats.problems.total == 0


@pytest.mark.parametrize("value", [None, "", "  "])
def test_a_missing_date_is_not_a_problem(tmp_path: Path, oldp_record: Rec, value: object) -> None:
    row = {**oldp_record("labour_lag_hessen"), "date": value}
    (tmp_path / "a.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    loader = OldpLoader()
    (doc,) = loader.load(tmp_path)
    assert doc.version_date is None
    assert loader.stats.problems.total == 0


def test_graph_result_type_is_unchanged(oldp_graph_raw: Path) -> None:
    result = load_citation_graph(oldp_graph_raw)
    assert all(isinstance(k, str) for k in result)
    assert DocId("oldp-446202") in result
