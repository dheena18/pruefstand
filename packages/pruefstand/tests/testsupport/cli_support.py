"""Helpers of the CLI command tests (T1.10): invoke ``run`` and ``gate``, read what they wrote."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner, Result

from pruefstand.cli import app


def run_dir(result: Result) -> Path:
    """The run directory a successful ``run`` printed."""
    assert result.exit_code == 0, result.output
    return Path(result.stdout.strip().splitlines()[-1])


def do_run(cli: CliRunner, config: Path, out: Path, *extra: str) -> Result:
    """Invoke ``pruefstand run --tier pr``."""
    return cli.invoke(
        app, ["run", "--config", str(config), "--tier", "pr", "--out", str(out), *extra]
    )


def gate(cli: CliRunner, config: Path, candidate: Path, baseline: Path, *extra: str) -> Result:
    """Invoke ``pruefstand gate`` for two run directories."""
    args = ["gate", "--config", str(config), "--candidate", str(candidate)]
    return cli.invoke(app, [*args, "--baseline", str(baseline), *extra])


def manifest_of(result: Result) -> dict[str, Any]:
    """``run.json`` of the run a successful ``run`` printed."""
    data: dict[str, Any] = json.loads((run_dir(result) / "run.json").read_text(encoding="utf-8"))
    return data
