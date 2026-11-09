"""scripts/models/gh_models_budget.py: the daily call ledger of cassettes-models.yml (D900)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from models.gh_models_budget import (
    add_calls,
    count_files,
    hit_ratio,
    main,
    remaining,
    summary_line,
    used_today,
)

SCRIPT = Path(__file__).resolve().parents[1] / "gh_models_budget.py"
DAY = "2026-11-09"


def test_a_missing_ledger_means_nothing_used(tmp_path: Path) -> None:
    assert used_today(tmp_path / "none.json", DAY) == 0


def test_calls_add_up_within_a_day_and_reset_on_the_next(tmp_path: Path) -> None:
    ledger = tmp_path / "sub" / "ledger.json"
    assert add_calls(ledger, DAY, 30) == 30
    assert add_calls(ledger, DAY, 12) == 42
    assert used_today(ledger, DAY) == 42
    assert used_today(ledger, "2026-11-10") == 0
    assert add_calls(ledger, "2026-11-10", 5) == 5
    assert json.loads(ledger.read_text(encoding="utf-8")) == {"date": "2026-11-10", "calls": 5}


def test_a_corrupt_ledger_counts_as_empty(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("{not json", encoding="utf-8")
    assert used_today(ledger, DAY) == 0
    ledger.write_text('{"date": "2026-11-09", "calls": "many"}', encoding="utf-8")
    assert used_today(ledger, DAY) == 0


@pytest.mark.parametrize(
    ("used", "cap", "asked", "expected"),
    [(0, 120, 100, 100), (30, 120, 100, 90), (120, 120, 10, 0), (200, 120, 10, 0), (0, 120, 0, 0)],
)
def test_remaining_is_capped_by_the_day_and_by_the_request(
    used: int, cap: int, asked: int, expected: int
) -> None:
    assert remaining(used, cap, asked) == expected


def test_negative_calls_are_ignored(tmp_path: Path) -> None:
    assert add_calls(tmp_path / "l.json", DAY, -5) == 0


def test_count_files_counts_cassettes_recursively(tmp_path: Path) -> None:
    (tmp_path / "rewrite").mkdir()
    (tmp_path / "rewrite" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    assert count_files(tmp_path) == 2
    assert count_files(tmp_path / "missing") == 0


def test_hit_ratio_and_summary_row() -> None:
    assert hit_ratio(3, 1) == 0.75
    assert hit_ratio(0, 0) == 0.0
    assert (
        summary_line("indomain_dev", 20, 80, 20, 120)
        == "| indomain_dev | 20 | 80 | 80% | 20 / 120 |"
    )


def test_cli_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = str(tmp_path / "ledger.json")
    assert main(["add", "--ledger", ledger, "--calls", "40"]) == 0
    assert capsys.readouterr().out.strip() == "40"
    args = ["remaining", "--ledger", ledger, "--daily-cap", "120", "--requested", "100"]
    assert main(args) == 0
    assert capsys.readouterr().out.strip() == "80"
    assert main(["used", "--ledger", ledger]) == 0
    assert capsys.readouterr().out.strip() == "40"


def test_script_runs_as_a_program(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    run = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "count", "--dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert run.stdout.strip() == "1"
