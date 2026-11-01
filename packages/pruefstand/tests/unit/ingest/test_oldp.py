"""OldpLoader (T2.3): the pinned 1k court-decision sample -> Document, hardened against bad input.

The fixtures in ``tests/fixtures/oldp`` are three real records of the sample, trimmed at tag
boundaries; in ``labour_lag_hessen`` every non-ASCII character is written as a named entity
(``K&uuml;ndigung``) because the dump mixes entity styles and the loader must decode all of them.
"""

import copy
import json
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pruefstand.ingest.oldp import OldpLimits, OldpLoader, main
from pruefstand.ingest.records import OldpDataError

from pruefstand.core.enums import Lang
from pruefstand.core.models.corpus import Document
from pruefstand.core.protocols import Loader

Rec = Callable[[str], dict[str, object]]  # the oldp_record fixture
Writer = Callable[[Path, Sequence[Mapping[str, object]]], Path]  # the write_jsonl fixture


def record(base: dict[str, object], **changes: object) -> dict[str, object]:
    row = copy.deepcopy(base)
    row.update(changes)
    return row


def docs_of(raw: Path, limits: OldpLimits | None = None) -> tuple[list[Document], OldpLoader]:
    loader = OldpLoader(limits) if limits else OldpLoader()
    return list(loader.load(raw)), loader


def test_protocol_conformance() -> None:
    assert isinstance(OldpLoader(), Loader)


def test_labour_decision_fields(oldp_raw: Path) -> None:
    docs, loader = docs_of(oldp_raw)
    doc = next(d for d in docs if d.doc_id == "oldp-446202")
    assert doc.metadata["jurisdiction"] == "Arbeitsgericht"
    assert doc.metadata["tenant_domain"] == "labour"
    assert "2 Sa 372/13" in doc.title
    assert doc.title == "Hessisches Landesarbeitsgericht 2014-02-26 2 Sa 372/13"
    assert doc.license == "ODbL-1.0"
    assert doc.lang is Lang.DE
    assert doc.tenant == "unassigned"
    assert doc.source == "oldp:decisions"
    assert doc.version_date == date(2014, 2, 26)
    assert doc.law_abbrev is None
    assert doc.metadata["court"] == "Hessisches Landesarbeitsgericht"
    assert doc.metadata["file_number"] == "2 Sa 372/13"
    assert doc.metadata["ecli"] == "ECLI:DE:LAGHE:2014:0226.2SA372.13.0A"
    assert doc.metadata["slug"] == "laghe-2014-02-26-2-sa-37213"
    assert loader.stats.decisions == 3
    assert loader.stats.problems == []


def test_html_is_removed_and_entities_are_decoded(oldp_raw: Path) -> None:
    docs, _ = docs_of(oldp_raw)
    for doc in docs:
        assert "<p>" not in doc.text
        assert "<div" not in doc.text
        assert "&uuml;" not in doc.text
    labour = next(d for d in docs if d.doc_id == "oldp-446202")
    assert "Kündigung" in labour.text
    assert "Tenor" in labour.text.split("\n")


def test_insurance_and_plain_court_domains(oldp_raw: Path) -> None:
    docs = {d.doc_id: d for d in docs_of(oldp_raw)[0]}
    insurance = docs["oldp-299231"]
    assert insurance.metadata["jurisdiction"] == "Zivilgericht"
    assert insurance.metadata["tenant_domain"] == "insurance"
    assert insurance.metadata["court_level"] == "Amtsgericht"
    other = docs["oldp-487573"]
    assert other.metadata["jurisdiction"] == "Verwaltungsgericht"
    assert other.metadata["tenant_domain"] == "other"
    assert "ecli" not in other.metadata  # empty values are left out


def test_parquet_and_jsonl_give_the_same_documents(oldp_raw: Path, tmp_path: Path) -> None:
    rows = [
        json.loads(line) for line in (oldp_raw / "decisions.jsonl").read_text("utf-8").splitlines()
    ]
    parquet_dir = tmp_path / "pq" / "oldp_decisions" / "dump-20260520-1k"
    parquet_dir.mkdir(parents=True)
    pl.from_dicts(rows).write_parquet(parquet_dir / "train-00000-of-00001.parquet")
    from_parquet, _ = docs_of(tmp_path / "pq" / "oldp_decisions")
    from_jsonl, _ = docs_of(oldp_raw)
    assert from_parquet == from_jsonl
    assert len(from_parquet) == 3


def test_scripts_styles_and_comments_are_dropped(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    html = "<p>Vor</p><script>alert('x')</script><style>p{}</style><!-- geheim --><p>Nach</p>"
    write_jsonl(tmp_path / "a.jsonl", [record(oldp_record("labour_lag_hessen"), content=html)])
    (doc,), _ = docs_of(tmp_path)
    assert doc.text == "Vor\nNach"


def test_text_is_nfc_and_hyphenation_is_joined(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    html = "<p>Kündi-\ngung der Arbeits-\nverhältnisse</p>"
    write_jsonl(tmp_path / "a.jsonl", [record(oldp_record("labour_lag_hessen"), content=html)])
    (doc,), _ = docs_of(tmp_path)
    assert doc.text == "Kündigung der Arbeitsverhältnisse"


def test_randnummern_stay_on_their_own_lines(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    html = (
        '<h4>Tatbestand</h4><dl class="RspDL"><dt><a name="rd_1">1</a></dt><dd><p>Erster Absatz.</p></dd></dl>'
        '<dl class="RspDL"><dt>2</dt><dd><p>Zweiter Absatz.</p></dd></dl>'
    )
    write_jsonl(tmp_path / "a.jsonl", [record(oldp_record("labour_lag_hessen"), content=html)])
    (doc,), _ = docs_of(tmp_path)
    assert doc.text.split("\n") == ["Tatbestand", "1", "Erster Absatz.", "2", "Zweiter Absatz."]


def test_empty_content_is_a_document_without_text(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    row = record(oldp_record("labour_lag_hessen"), content="", court={"name": "Unknown court"})
    write_jsonl(tmp_path / "a.jsonl", [row])
    (doc,), loader = docs_of(tmp_path)
    assert doc.text == ""
    assert doc.metadata["jurisdiction"] == "Sonstige"
    assert loader.stats.decisions == 1
    assert loader.stats.empty == 1
    assert loader.stats.problems == []


def test_bad_date_keeps_the_document_without_version_date(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    write_jsonl(tmp_path / "a.jsonl", [record(oldp_record("labour_lag_hessen"), date="gestern")])
    (doc,), _ = docs_of(tmp_path)
    assert doc.version_date is None


def problems_of(loader: OldpLoader) -> list[str]:
    return [p.kind for p in loader.stats.problems]


def test_bad_records_are_counted_and_loading_continues(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    base = oldp_record("labour_lag_hessen")
    rows = [
        record(base, id="abc"),                       # id is not an integer
        record(base, content=None),                   # content is not text
        record(base, court="Landgericht"),            # court is not an object
        record(base),                                 # fine
        record(base),                                 # duplicate id
    ]  # fmt: skip
    write_jsonl(tmp_path / "a.jsonl", rows)
    docs, loader = docs_of(tmp_path)
    assert [d.doc_id for d in docs] == ["oldp-446202"]
    assert problems_of(loader) == ["bad_record", "bad_record", "bad_record", "duplicate_id"]


def test_json_syntax_error_and_oversized_line_are_counted(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    path = write_jsonl(tmp_path / "a.jsonl", [oldp_record("labour_lag_hessen")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps(oldp_record("insurance_ag_duesseldorf"), ensure_ascii=False) + "\n")
    docs, loader = docs_of(tmp_path, OldpLimits(max_record_bytes=40_000))
    assert [d.doc_id for d in docs] == ["oldp-446202", "oldp-299231"]
    assert problems_of(loader) == ["bad_json"]
    docs, loader = docs_of(tmp_path, OldpLimits(max_record_bytes=1000))
    assert len(docs) == 0
    assert sorted(problems_of(loader)) == ["bad_json", "record_too_large", "record_too_large"]


def test_content_over_the_cap_is_skipped(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    base = oldp_record("labour_lag_hessen")
    write_jsonl(
        tmp_path / "a.jsonl",
        [record(base, content="<p>" + "a" * 1000 + "</p>"), record(base, id=5)],
    )
    docs, loader = docs_of(tmp_path, OldpLimits(max_content_chars=500))
    assert docs == []
    assert problems_of(loader) == ["content_too_large", "content_too_large"]


def test_file_over_the_cap_is_skipped(oldp_raw: Path) -> None:
    docs, loader = docs_of(oldp_raw, OldpLimits(max_file_bytes=1000))
    assert docs == []
    assert problems_of(loader) == ["file_too_large"]


def test_document_cap_stops_the_load(oldp_raw: Path) -> None:
    docs, loader = docs_of(oldp_raw, OldpLimits(max_documents=2))
    assert len(docs) == 2
    assert problems_of(loader) == ["too_many_documents"]


def test_unreadable_parquet_is_a_counted_problem(
    tmp_path: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    (tmp_path / "broken.parquet").write_bytes(b"PAR1 definitely not parquet")
    write_jsonl(tmp_path / "ok.jsonl", [oldp_record("labour_lag_hessen")])
    docs, loader = docs_of(tmp_path)
    assert len(docs) == 1
    assert problems_of(loader) == ["bad_file"]


def test_missing_directory_raises_and_empty_directory_is_a_problem(tmp_path: Path) -> None:
    with pytest.raises(OldpDataError):
        list(OldpLoader().load(tmp_path / "nope"))
    docs, loader = docs_of(tmp_path)
    assert docs == []
    assert problems_of(loader) == ["no_files"]


def test_hidden_cache_directories_are_ignored(
    oldp_raw: Path, oldp_record: Rec, write_jsonl: Writer
) -> None:
    write_jsonl(
        oldp_raw / ".cache" / "huggingface" / "stale.jsonl", [oldp_record("labour_lag_hessen")]
    )
    docs, _ = docs_of(oldp_raw)
    assert len(docs) == 3


def test_loading_never_opens_a_socket(oldp_raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        msg = "network access in the OLDP loader"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setenv("HF_DATASETS_OFFLINE", "1")
    assert len(docs_of(oldp_raw)[0]) == 3


def test_ids_titles_and_order_are_stable(oldp_raw: Path) -> None:
    first, _ = docs_of(oldp_raw)
    second, _ = docs_of(oldp_raw)
    assert first == second
    assert [d.doc_id for d in first] == ["oldp-446202", "oldp-299231", "oldp-487573"]


def test_cli_prints_the_stats_line(oldp_raw: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(oldp_raw), "--stats"]) == 0
    out = capsys.readouterr().out.strip()
    fields = dict(part.split("=") for part in out.split())
    assert list(fields) == ["decisions", "chunks", "no_sections", "errors"]
    assert fields["decisions"] == "3"
    assert int(fields["chunks"]) >= 6
    assert fields["no_sections"] == "1"
    assert fields["errors"] == "0"


def test_cli_exit_code_is_1_when_a_problem_was_counted(
    oldp_raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (oldp_raw / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")
    assert main([str(oldp_raw), "--stats"]) == 1
    captured = capsys.readouterr()
    assert captured.out.strip().endswith("errors=1")
    assert "bad_json" in captured.err


def test_cli_without_stats_prints_nothing(
    oldp_raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(oldp_raw)]) == 0
    assert capsys.readouterr().out == ""


def test_html_bombs_are_bounded(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    rows = [
        record(base, id=1, content="<div>" * 50_000 + "tief" + "</div>" * 50_000),
        record(base, id=2, content="<" * 300_000),
        record(base, id=3, content="<p>" * 100_000 + "x"),
    ]
    write_jsonl(tmp_path / "a.jsonl", rows)
    start = time.perf_counter()
    docs, loader = docs_of(tmp_path)
    assert time.perf_counter() - start < 20
    assert len(docs) + len(loader.stats.problems) == 3


def test_loader_time_is_linear(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    times: dict[int, float] = {}
    for paragraphs in (2_000, 16_000):
        html = "<p>Die Kündigung &uuml;ber § 622 BGB wurde erklärt.</p>" * paragraphs
        directory = tmp_path / str(paragraphs)
        write_jsonl(directory / "a.jsonl", [record(base, content=html)])
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            list(OldpLoader().load(directory))
            best = min(best, time.perf_counter() - start)
        times[paragraphs] = best
    assert times[16_000] / times[2_000] < 20  # linear = 8, quadratic = 64
