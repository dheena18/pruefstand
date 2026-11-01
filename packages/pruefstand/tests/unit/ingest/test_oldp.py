"""OldpLoader (T2.3): the pinned 1k court-decision sample -> Document, hardened against bad input.

The fixtures in ``tests/fixtures/oldp`` are three real records of the sample, trimmed at tag
boundaries; in ``labour_lag_hessen`` every non-ASCII character is written as a named entity
(``K&uuml;ndigung``) because the dump mixes entity styles and the loader must decode all of them.
"""

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId
from pruefstand.core.models.corpus import Document
from pruefstand.core.protocols import Loader
from pruefstand.ingest.oldp import OldpLimits, OldpLoader, main

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
    insurance = docs[DocId("oldp-299231")]
    assert insurance.metadata["jurisdiction"] == "Zivilgericht"
    assert insurance.metadata["tenant_domain"] == "insurance"
    assert insurance.metadata["court_level"] == "Amtsgericht"
    other = docs[DocId("oldp-487573")]
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
        '<h4>Tatbestand</h4><dl class="RspDL"><dt><a name="rd_1">1</a></dt>'
        "<dd><p>Erster Absatz.</p></dd></dl>"
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


def test_ids_titles_and_order_are_stable(oldp_raw: Path) -> None:
    first, _ = docs_of(oldp_raw)
    second, _ = docs_of(oldp_raw)
    assert first == second
    assert [d.doc_id for d in first] == ["oldp-446202", "oldp-299231", "oldp-487573"]


def test_cli_prints_the_stats_line(oldp_raw: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(oldp_raw), "--stats"]) == 0
    out = capsys.readouterr().out.strip()
    fields = dict(part.split("=") for part in out.split())
    assert list(fields) == ["decisions", "chunks", "no_sections", "errors", "trailer_chars"]
    assert fields["trailer_chars"] == "0"
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
    assert captured.out.strip().endswith("errors=1 trailer_chars=0")
    assert "bad_json" in captured.err


def test_cli_without_stats_prints_nothing(
    oldp_raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(oldp_raw)]) == 0
    assert capsys.readouterr().out == ""
