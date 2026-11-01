"""`python -m pruefstand.ingest.gii_xml <raw_dir> --stats` and the counters (T2.2, S6/S7)."""

import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from pruefstand.ingest.gii.stats import GiiStats
from pruefstand.ingest.gii_xml import GiiXmlLoader, main

RawFactory = Callable[[Mapping[str, Mapping[str, bytes]]], Path]


def test_stats_table_lists_every_law_and_the_total(
    raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(raw_dir), "--stats"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == [
        "law",
        "norms",
        "skipped",
        "docs",
        "chunks",
        "errors",
        "version_date",
    ]
    rows = {ln.split()[0]: ln.split() for ln in lines[1:]}
    assert rows["BGB"][1:6] == ["7", "4", "3", "3", "0"]
    assert rows["BGB"][6] == "2026-09-26"
    assert set(rows) == {"AktG", "ArbZG", "BGB", "EGBGB", "KSchG", "TOTAL"}
    assert rows["TOTAL"][3] == str(sum(int(rows[k][3]) for k in rows if k != "TOTAL"))


def test_without_stats_nothing_is_printed(
    raw_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(raw_dir)]) == 0
    assert capsys.readouterr().out == ""


def test_problems_give_exit_code_1_and_are_listed_on_stderr(
    make_raw: RawFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = make_raw({"bad": {"../x.xml": b"<a/>"}})
    assert main([str(raw), "--stats"]) == 1
    captured = capsys.readouterr()
    assert "error: bad: unsafe_archive" in captured.err
    assert captured.out.splitlines()[-1].split()[0] == "TOTAL"
    assert any(ln.startswith("bad ") for ln in captured.out.splitlines())


def test_module_entry_point_runs(raw_dir: Path) -> None:
    result = subprocess.run(  # noqa: S603  (fixed argv, no shell)
        [sys.executable, "-I", "-m", "pruefstand.ingest.gii_xml", str(raw_dir), "--stats"],
        capture_output=True, text=True, check=False, timeout=60,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert "BGB" in result.stdout


def test_uncitable_two_letter_number_is_a_counted_skip_not_an_error(
    make_raw: RawFactory, fixture_dir: Path
) -> None:
    raw = make_raw({"kwg": {"k.xml": (fixture_dir / "kwg_53ca.xml").read_bytes()}})
    loader = GiiXmlLoader()
    docs = [str(d.doc_id) for d in loader.load(raw)]
    assert docs == ["gii-kwg-25a"]
    law = loader.stats.laws["KWG"]
    assert law.skipped == {"header": 1, "uncitable": 1}
    assert law.errors == 0
    assert loader.stats.error_count == 0


def test_record_chunks_creates_the_law_row() -> None:
    stats = GiiStats()
    stats.record_chunks("BGB", 3)
    stats.record_chunks("BGB", 2)
    assert stats.laws["BGB"].chunks == 5
