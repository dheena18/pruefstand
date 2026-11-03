"""OldpLoader hardening (T2.3): bad records, size caps, bombs, linear time."""

import copy
import json
import socket
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from testsupport.timing import assert_scales_linearly, cpu_budget

from pruefstand.core.models.corpus import Document
from pruefstand.ingest.oldp import OldpLimits, OldpLoader
from pruefstand.ingest.records import OldpDataError

Rec = Callable[[str], dict[str, object]]  # the oldp_record fixture
Writer = Callable[[Path, Sequence[Mapping[str, object]]], Path]  # the write_jsonl fixture


def record(base: dict[str, object], **changes: object) -> dict[str, object]:
    row = copy.deepcopy(base)
    row.update(changes)
    return row


def docs_of(raw: Path, limits: OldpLimits | None = None) -> tuple[list[Document], OldpLoader]:
    loader = OldpLoader(limits) if limits else OldpLoader()
    return list(loader.load(raw)), loader


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


def test_html_bombs_are_bounded(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    rows = [
        record(base, id=1, content="<div>" * 50_000 + "tief" + "</div>" * 50_000),
        record(base, id=2, content="<" * 300_000),
        record(base, id=3, content="<p>" * 100_000 + "x"),
    ]
    write_jsonl(tmp_path / "a.jsonl", rows)
    with cpu_budget(20):
        docs, loader = docs_of(tmp_path)
    assert len(docs) + len(loader.stats.problems) == 3


def _load_all(directory: Path) -> Callable[[], object]:
    return lambda: list(OldpLoader().load(directory))


def test_loader_time_is_linear(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    base = oldp_record("labour_lag_hessen")
    loaders: dict[int, Callable[[], object]] = {}
    for paragraphs in (2_000, 16_000):
        html = "<p>Die Kündigung &uuml;ber § 622 BGB wurde erklärt.</p>" * paragraphs
        directory = tmp_path / str(paragraphs)
        write_jsonl(directory / "a.jsonl", [record(base, content=html)])
        loaders[paragraphs] = _load_all(directory)
    # linear = 8, quadratic = 64
    assert_scales_linearly(loaders[2_000], loaders[16_000], scale=8)


def test_boolean_ids_are_rejected(tmp_path: Path, oldp_record: Rec, write_jsonl: Writer) -> None:
    write_jsonl(tmp_path / "a.jsonl", [record(oldp_record("labour_lag_hessen"), id=True)])
    docs, loader = docs_of(tmp_path)
    assert docs == []
    assert problems_of(loader) == ["bad_record"]
