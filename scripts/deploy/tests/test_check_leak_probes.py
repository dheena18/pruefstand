"""scripts/deploy/check_leak_probes.py on real raw runs of the dashboard fixtures (T8.1, Y7.3)."""

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deploy.check_leak_probes import main

RAW = Path(__file__).resolve().parents[3] / "apps" / "dashboard" / "fixtures" / "raw"
CLEAN = RAW / "20261103T123537-e01927"
HARD_FAIL = RAW / "20261103T124130-8ee0ce"  # tenant_filter: post_topk, tenant_leak = 1
INCOMPLETE = RAW / "20261103T123637-fa58d9"  # budget_exceeded


def test_a_clean_probe_run_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(CLEAN)]) == 0
    out = capsys.readouterr().out
    assert "clean" in out
    assert "injection_success:" in out


def test_the_real_hard_fail_run_names_case_and_metric(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(HARD_FAIL)]) == 1
    err = capsys.readouterr().err
    assert "slice-009: tenant_leak = 1" in err
    assert "slice-022: tenant_leak = 1" in err


def test_an_incomplete_run_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(INCOMPLETE)]) == 1
    assert "run incomplete (stop_reason 'budget_exceeded')" in capsys.readouterr().err


def test_a_run_that_scored_none_of_the_hard_metrics_is_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "run"
    shutil.copytree(CLEAN, run)
    table = pq.read_table(run / "results.parquet")
    keep = [
        m not in ("canary_leak", "system_prompt_leak") for m in table.column("metric").to_pylist()
    ]
    pq.write_table(table.filter(pa.array(keep)), run / "results.parquet")
    assert main([str(run)]) == 1
    err = capsys.readouterr().err
    assert "no canary_leak result" in err
    assert "no system_prompt_leak result" in err
    assert "no tenant_leak result" not in err


def test_an_unreadable_run_dir_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path)]) == 2
    assert "cannot read" in capsys.readouterr().err
    (tmp_path / "run.json").write_text("not json")
    assert main([str(tmp_path)]) == 2
