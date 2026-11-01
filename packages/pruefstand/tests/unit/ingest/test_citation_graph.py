"""load_citation_graph (T2.3 S6): OLDP citation edges -> normalised law keys per decision."""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import polars as pl
import pytest
from structlog.testing import capture_logs

from pruefstand.core.ids import DocId
from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.ingest.records import OldpDataError

Writer = Callable[[Path, Sequence[Mapping[str, object]]], Path]


def edge(
    slug: str, code: str | None, section: str | None, to_type: str = "Law"
) -> dict[str, object]:
    return {
        "from_slug": slug, "from_type": "Case", "to_type": to_type,
        "to_law_book_code": code, "to_law_section": section, "to_slug": "x",
    }  # fmt: skip


LABOUR = "laghe-2014-02-26-2-sa-37213"


def test_edges_become_sorted_normalised_keys_per_decision(oldp_graph_raw: Path) -> None:
    graph = load_citation_graph(oldp_graph_raw)
    assert graph[DocId("oldp-446202")] == ("§ 1 KSchG", "§ 622 BGB")


def test_unknown_law_is_kept_as_is_and_logged(oldp_graph_raw: Path) -> None:
    with capture_logs() as logs:
        graph = load_citation_graph(oldp_graph_raw)
    assert graph[DocId("oldp-299231")] == ("§ 5 FMStFG",)
    unknown = [entry for entry in logs if entry["event"] == "citation_unknown_law"]
    assert [entry["law"] for entry in unknown] == ["FMStFG"]


def test_case_to_case_edges_and_unresolved_slugs_are_left_out(oldp_graph_raw: Path) -> None:
    with capture_logs() as logs:
        graph = load_citation_graph(oldp_graph_raw)
    assert set(graph) == {
        "oldp-446202",
        "oldp-299231",
    }  # the Stuttgart decision is not in the sample
    summary = next(entry for entry in logs if entry["event"] == "citation_graph_loaded")
    assert (summary["decisions"], summary["edges"], summary["unresolved"]) == (2, 3, 1)


def test_explicit_decisions_directory(oldp_graph_raw: Path, tmp_path: Path, oldp_raw: Path) -> None:
    moved = tmp_path / "elsewhere" / "graph"
    moved.mkdir(parents=True)
    (moved / "edges.jsonl").write_bytes((oldp_graph_raw / "edges.jsonl").read_bytes())
    with pytest.raises(OldpDataError):
        load_citation_graph(moved)  # no ../oldp_decisions next to it
    assert load_citation_graph(moved, decisions_dir=oldp_raw)[DocId("oldp-446202")] == (
        "§ 1 KSchG",
        "§ 622 BGB",
    )


def test_missing_graph_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(OldpDataError):
        load_citation_graph(tmp_path / "nope")


def test_real_column_names_and_forms_of_the_dump(
    oldp_raw: Path, tmp_path: Path, write_jsonl: Writer
) -> None:
    graph_dir = oldp_raw.parent / "oldp_citation_graph"
    rows = [
        edge(LABOUR, "Grundgesetz", "Artikel 3"),
        edge(LABOUR, "AO 1977", "§ 42"),
        edge(LABOUR, "KSchG", "§ 1"),
        edge(LABOUR, "KSchG", "§ 1"),  # duplicate edge
        edge(LABOUR, "BGB", "§ 626"),
        edge(LABOUR, None, None, "Case"),
    ]
    write_jsonl(graph_dir / "e.jsonl", rows)
    (key,) = load_citation_graph(graph_dir).items()
    assert key == ("oldp-446202", ("Art. 3 GG", "§ 1 KSchG", "§ 42 AO 1977", "§ 626 BGB"))


def test_parquet_edges_with_the_real_schema(oldp_raw: Path) -> None:
    graph_dir = oldp_raw.parent / "oldp_citation_graph" / "dump-20260520-1k"
    graph_dir.mkdir(parents=True)
    frame = pl.DataFrame(
        {
            "from_slug": [LABOUR, LABOUR, "unbekannt"],
            "from_type": ["Case"] * 3,
            "to_type": ["Law"] * 3,
            "to_law_book_code": ["BGB", "KSchG", "BGB"],
            "to_law_section": ["§ 622", "§ 1", "§ 1"],
            "to_slug": ["622", "1", "1"],
            "from_case_court_name": ["a", "b", "c"],  # the dump has 20 more columns
        }
    )
    frame.write_parquet(graph_dir / "train-00000-of-00001.parquet")
    assert load_citation_graph(graph_dir.parent) == {"oldp-446202": ("§ 1 KSchG", "§ 622 BGB")}


def test_rows_with_missing_fields_are_skipped(oldp_graph_raw: Path) -> None:
    with (oldp_graph_raw / "edges.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"from_slug": LABOUR, "from_type": "Case", "to_type": "Law"}) + "\n"
        )
        handle.write("{broken\n")
        handle.write(json.dumps(edge(LABOUR, "BGB", "")) + "\n")
    assert load_citation_graph(oldp_graph_raw)[DocId("oldp-446202")] == ("§ 1 KSchG", "§ 622 BGB")


def test_result_is_stable_across_runs(oldp_graph_raw: Path) -> None:
    assert load_citation_graph(oldp_graph_raw) == load_citation_graph(oldp_graph_raw)


def test_many_distinct_unknown_laws_are_logged_once_each_and_fast(
    oldp_raw: Path, write_jsonl: Writer
) -> None:
    graph_dir = oldp_raw.parent / "oldp_citation_graph"
    rows = [edge(LABOUR, f"Gesetz{i % 50}", f"§ {i}") for i in range(20_000)]
    write_jsonl(graph_dir / "e.jsonl", rows)
    start = time.perf_counter()
    with capture_logs() as logs:
        graph = load_citation_graph(graph_dir)
    assert time.perf_counter() - start < 20
    assert len(graph[DocId("oldp-446202")]) == 20_000
    assert len([entry for entry in logs if entry["event"] == "citation_unknown_law"]) == 50
