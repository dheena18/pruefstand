"""Hostile input stays bounded (T2.3 re-review): huge numbers, bad-row floods, surrogates, dates."""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import polars as pl
import pytest
from testsupport.rss import PeakRss

from pruefstand.core.ids import DocId
from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.ingest.oldp import OldpLimits, OldpLoader, main
from pruefstand.ingest.records import OldpDataError, Problem, ProblemLog

Rec = Callable[[str], dict[str, object]]
Writer = Callable[[Path, Sequence[Mapping[str, object]]], Path]
MIB = 1024 * 1024


def kinds(log: list[Problem]) -> list[str]:
    return [p.kind for p in log]


def test_problem_log_counts_all_and_stores_few() -> None:
    log = ProblemLog(max_examples=5)
    for i in range(1000):
        log.append(Problem("f", "bad_record", str(i)))
    log.append(Problem("f", "rare", "x"))
    assert (log.total, log.counts) == (1001, {"bad_record": 1000, "rare": 1})
    assert len(log) == 6  # the first five plus the first of the new kind
    assert log[0].detail == "0"
    assert ProblemLog() == []


def test_huge_integers_floats_and_deep_nesting_are_counted_problems(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    path = write_jsonl(tmp_path / "a.jsonl", [oldp_record("labour_lag_hessen")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": ' + "9" * 10_000 + ', "content": "x"}\n')
        handle.write('{"id": 1e999999, "content": "x"}\n')
        handle.write('{"id": ' + "9" * 4000 + ', "content": "x"}\n')
        handle.write("[" * 100_000 + "]" * 100_000 + "\n")
        handle.write(json.dumps(oldp_record("insurance_ag_duesseldorf")) + "\n")
    loader = OldpLoader()
    docs = list(loader.load(tmp_path))
    assert [d.doc_id for d in docs] == ["oldp-446202", "oldp-299231"]
    assert kinds(loader.stats.problems) == ["bad_json", "bad_record", "bad_record", "bad_json"]


def test_graph_survives_huge_integers(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    decisions = write_jsonl(
        tmp_path / "oldp_decisions" / "a.jsonl", [oldp_record("labour_lag_hessen")]
    )
    with decisions.open("a", encoding="utf-8") as handle:
        handle.write('{"id": ' + "9" * 10_000 + ', "slug": "x"}\n')
    edge = {"from_slug": "laghe-2014-02-26-2-sa-37213", "from_type": "Case", "to_type": "Law"}
    graph = write_jsonl(
        tmp_path / "oldp_citation_graph" / "e.jsonl",
        [{**edge, "to_law_book_code": "BGB", "to_law_section": "§ 1"}],
    )
    with graph.open("a", encoding="utf-8") as handle:
        handle.write('{"x": ' + "9" * 10_000 + "}\n")
    problems: list[Problem] = []
    result = load_citation_graph(graph.parent, problems=problems)
    assert result == {DocId("oldp-446202"): ("§ 1 BGB",)}
    assert kinds(problems) == ["bad_json", "bad_json"]


def test_flood_of_bad_jsonl_rows_is_capped(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text("{}\n" * 120_000, encoding="utf-8")
    loader = OldpLoader(OldpLimits(max_rows=20_000))
    with PeakRss() as rss:
        assert list(loader.load(tmp_path)) == []
    problems = loader.stats.problems
    assert problems.counts == {"bad_record": 20_000, "too_many_rows": 1}
    assert problems.total == 20_001
    assert len(problems) <= 110
    assert "too_many_rows" in kinds(problems)
    assert rss.grown_kib < 80 * 1024


def test_flood_of_bad_parquet_rows_is_capped(tmp_path: Path) -> None:
    pl.DataFrame({"id": [0] * 60_000, "content": ["x"] * 60_000}).write_parquet(
        tmp_path / "a.parquet"
    )
    loader = OldpLoader(OldpLimits(max_rows=5_000))
    with PeakRss() as rss:
        assert list(loader.load(tmp_path)) == []
    assert loader.stats.problems.counts == {"bad_record": 5_000, "too_many_rows": 1}
    assert rss.grown_kib < 80 * 1024


def test_cli_exit_code_and_count_reflect_the_true_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.jsonl").write_text("{}\n" * 30_000, encoding="utf-8")
    assert main([str(tmp_path), "--stats"]) == 1
    captured = capsys.readouterr()
    assert "errors=30000 " in captured.out
    assert captured.err.count("\n") < 60


def test_graph_truncation_is_a_counted_problem(oldp_raw: Path, tmp_path: Path) -> None:
    graph = oldp_raw.parent / "oldp_citation_graph"
    graph.mkdir()
    edge = {"from_slug": "laghe-2014-02-26-2-sa-37213", "from_type": "Case", "to_type": "Law"}
    rows = [{**edge, "to_law_book_code": "BGB", "to_law_section": "§ 1"}] + [{}] * 30_000
    (graph / "e.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    log = ProblemLog()
    result = load_citation_graph(graph, limits=OldpLimits(max_rows=10_000), problems=log)
    assert result == {DocId("oldp-446202"): ("§ 1 BGB",)}
    assert log.counts == {"too_many_rows": 1}


def test_slug_scan_is_capped_and_fails_closed(tmp_path: Path, oldp_record: Rec) -> None:
    decisions = tmp_path / "oldp_decisions"
    decisions.mkdir()
    lines = "{}\n" * 30_000 + json.dumps(oldp_record("labour_lag_hessen")) + "\n"
    (decisions / "a.jsonl").write_text(lines, encoding="utf-8")
    graph = tmp_path / "oldp_citation_graph"
    graph.mkdir()
    edge = {
        "from_slug": "laghe-2014-02-26-2-sa-37213",
        "from_type": "Case",
        "to_type": "Law",
        "to_law_book_code": "BGB",
        "to_law_section": "§ 1",
    }
    (graph / "e.jsonl").write_text(json.dumps(edge) + "\n", encoding="utf-8")
    log = ProblemLog()
    with pytest.raises(OldpDataError, match="resolve"):
        load_citation_graph(graph, limits=OldpLimits(max_rows=10_000), problems=log)
    assert log.counts["too_many_rows"] == 1


def test_lone_surrogates_are_a_counted_problem(tmp_path: Path, oldp_record: Rec) -> None:
    good = json.dumps(oldp_record("labour_lag_hessen"))
    lines = [
        '{"id": 5, "content": "\\ud800x", "court": {}}',
        '{"id": 6, "content": "x", "court": {"name": "Amts\\udc00gericht"}}',
        '{"id": 7, "content": "x", "file_number": "\\ud800"}',
        good,
    ]
    (tmp_path / "a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    loader = OldpLoader()
    docs = list(loader.load(tmp_path))
    assert [d.doc_id for d in docs] == ["oldp-446202"]
    assert kinds(loader.stats.problems) == ["bad_record"] * 3


def test_impossible_date_is_a_problem_and_not_in_the_title(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    row = {**oldp_record("labour_lag_hessen"), "date": "2020-13-45"}
    write_jsonl(tmp_path / "a.jsonl", [row])
    loader = OldpLoader()
    (doc,) = loader.load(tmp_path)
    assert doc.version_date is None
    assert "2020" not in doc.title
    assert kinds(loader.stats.problems) == ["bad_date"]


def test_default_group_cap_is_128_mib() -> None:
    assert OldpLimits().max_group_bytes == 128 * MIB
    assert OldpLimits().max_rows == 100_000
