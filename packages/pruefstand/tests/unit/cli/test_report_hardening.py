"""T1.10a: ``pruefstand report`` checks gate.json against the run it is read next to."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from pruefstand.cli import app


def report(cli: CliRunner, run: Path, fmt: str = "md") -> Result:
    return cli.invoke(app, ["report", "--run", str(run), "--format", fmt])


def edit_gate(run: Path, **changes: object) -> None:
    path = run / "gate.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, **changes}), encoding="utf-8")


def baseline_of(run: Path) -> Path:
    return next(p for p in run.parent.iterdir() if p != run)


@pytest.mark.parametrize("fmt", ["md", "html"])
def test_a_gate_json_of_another_candidate_is_a_usage_error(
    cli: CliRunner, gated_pair: Path, fmt: str
) -> None:
    edit_gate(gated_pair, candidate_run_id="20261102T220009-ffffff")
    result = report(cli, gated_pair, fmt)
    assert result.exit_code == 2
    assert "20261102T220009-ffffff" in result.output


@pytest.mark.parametrize("bad", ["../elsewhere", "a/b", "..", "/etc", "x\\y", ""])
@pytest.mark.parametrize("fmt", ["md", "html"])
def test_a_baseline_run_id_that_is_not_a_plain_name_is_a_usage_error(
    cli: CliRunner, gated_pair: Path, bad: str, fmt: str
) -> None:
    edit_gate(gated_pair, baseline_run_id=bad)
    result = report(cli, gated_pair, fmt)
    assert result.exit_code == 2, result.output
    assert "baseline_run_id" in result.output


def test_a_tampered_baseline_is_an_integrity_error_not_a_missing_baseline(
    cli: CliRunner, gated_pair: Path
) -> None:
    results = baseline_of(gated_pair) / "results.parquet"
    data = bytearray(results.read_bytes())
    data[len(data) // 2] ^= 0xFF
    results.write_bytes(bytes(data))
    result = report(cli, gated_pair)
    assert result.exit_code == 3
    assert "checksum" in result.output


def test_a_missing_baseline_still_renders(cli: CliRunner, gated_pair: Path) -> None:
    for item in baseline_of(gated_pair).iterdir():
        item.unlink()
    baseline_of(gated_pair).rmdir()
    assert report(cli, gated_pair).exit_code == 0
