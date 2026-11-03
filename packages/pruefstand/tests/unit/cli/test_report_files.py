"""``pruefstand report --format html|evidence`` writes into the run directory (T6.4)."""

import hashlib
import json
import shutil
from pathlib import Path

from testsupport.pipeline_support import config_file, mini_config
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.models.evidence import EvidenceRecord


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report(cli: CliRunner, run: Path, *args: str) -> Result:
    return cli.invoke(app, ["report", "--run", str(run), *args])


def test_html_is_written_next_to_gate_json(cli: CliRunner, gated_pair: Path) -> None:
    result = report(cli, gated_pair, "--format", "html")
    assert result.exit_code == 0, result.output
    text = (gated_pair / "report.html").read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "Content-Security-Policy" in text
    assert "Prüfstand report" in text
    assert str(gated_pair / "report.html") in result.stdout


def test_html_renders_without_the_baseline_run(cli: CliRunner, gated_pair: Path) -> None:
    base = next(p for p in gated_pair.parent.iterdir() if p != gated_pair)
    shutil.rmtree(base)
    assert report(cli, gated_pair, "--format", "html").exit_code == 0
    assert "Baseline answer" not in (gated_pair / "report.html").read_text(encoding="utf-8")


def test_evidence_needs_a_config(cli: CliRunner, gated_pair: Path) -> None:
    result = report(cli, gated_pair, "--format", "evidence")
    assert result.exit_code == 2
    assert "--config" in result.output
    assert not (gated_pair / "evidence.json").exists()


def test_evidence_fills_hashes_and_thresholds(
    cli: CliRunner, gated_pair: Path, good_config: Path
) -> None:
    result = report(cli, gated_pair, "--format", "evidence", "--config", str(good_config))
    assert result.exit_code == 0, result.output
    raw = (gated_pair / "evidence.json").read_text(encoding="utf-8")
    record = EvidenceRecord.model_validate_json(raw)
    gate = json.loads((gated_pair / "gate.json").read_text(encoding="utf-8"))
    baseline = gated_pair.parent / gate["baseline_run_id"]
    assert record.candidate.run_json_sha256 == sha256_of(gated_pair / "run.json")
    assert record.gate_json_sha256 == sha256_of(gated_pair / "gate.json")
    assert record.baseline is not None
    assert record.baseline.run_json_sha256 == sha256_of(baseline / "run.json")
    assert record.thresholds is not None
    assert "context_recall" in record.thresholds.metrics
    assert raw.endswith("}\n")


def test_evidence_with_a_foreign_config_is_a_usage_error(
    cli: CliRunner, gated_pair: Path, tmp_path: Path
) -> None:
    other = config_file(tmp_path / "other.yaml", mini_config(seed=99))
    result = report(cli, gated_pair, "--format", "evidence", "--config", str(other))
    assert result.exit_code == 2
    assert "config hash differs" in result.output
    assert not (gated_pair / "evidence.json").exists()
