"""``pruefstand gate``: compare a candidate run with a baseline run or a stored baseline."""

from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_FAIL, EXIT_USAGE, fail, guarded
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import GateReport
from pruefstand.pipeline.gate import GATE_FILE, gate_from_store, run_gate
from pruefstand.store.baseline_index import REFS

_WARNING = frozenset({GateStatus.WARN, GateStatus.UNSUPPORTED_CONFIG})
_Candidate = Annotated[Path, typer.Option("--candidate", help="Candidate run directory.")]
_Baseline = Annotated[Path | None, typer.Option("--baseline", help="Baseline run directory.")]
_FromStore = Annotated[
    bool, typer.Option("--from-store", help="Read the baseline from the baseline store.")
]
_Ref = Annotated[
    str | None, typer.Option("--ref", help=f"With --from-store: {', '.join(REFS)} (default main).")
]
_FailOnWarn = Annotated[bool, typer.Option("--fail-on-warn", help="Exit 1 on WARN as well.")]
_Config = Annotated[
    Path,
    typer.Option(
        "--config",
        envvar="PRUEFSTAND_CONFIG",
        help="Gate policy and seed (the pruefstand.yaml of the run).",
    ),
]


def _exit_code(report: GateReport, *, fail_on_warn: bool) -> None:
    if report.status is GateStatus.FAIL or (fail_on_warn and report.status in _WARNING):
        raise typer.Exit(EXIT_FAIL)


def _check_flags(
    candidate: Path, baseline: Path | None, *, from_store: bool, ref: str | None
) -> None:
    if from_store and baseline is not None:
        fail("error: give --baseline or --from-store, not both", EXIT_USAGE)
    if ref is not None and not from_store:
        fail("error: --ref needs --from-store", EXIT_USAGE)
    if ref is not None and ref not in REFS:
        fail(f"error: --ref must be one of {', '.join(REFS)}", EXIT_USAGE)
    if baseline is None and not from_store:
        fail("error: give --baseline <run directory> (or --from-store)", EXIT_USAGE)
    if baseline is not None and (
        candidate.resolve() == baseline.resolve() or candidate.name == baseline.name
    ):
        fail(
            "error: --candidate and --baseline are the same run; a run cannot gate itself",
            EXIT_USAGE,
        )


def gate_command(
    ctx: typer.Context,
    *,
    candidate: _Candidate,
    baseline: _Baseline = None,
    from_store: _FromStore = False,
    ref: _Ref = None,
    fail_on_warn: _FailOnWarn = False,
    config: _Config = Path("pruefstand.yaml"),
) -> None:
    """Write ``gate.json`` into the candidate directory; exit 1 on FAIL."""
    _check_flags(candidate, baseline, from_store=from_store, ref=ref)
    with guarded(ctx):
        cfg = load_config(config)
        if baseline is not None:
            report = run_gate(candidate, baseline, cfg)
        else:
            report = gate_from_store(candidate, cfg, ref=ref or "main")
        typer.echo(f"gate {report.status.value}: {candidate / GATE_FILE}")
        if report.no_baseline:
            typer.echo(f"no baseline for {report.eval_fingerprint}; run baseline-promote")
        _exit_code(report, fail_on_warn=fail_on_warn)


def register(app: typer.Typer) -> None:
    """Add the ``gate`` command to ``app``."""
    app.command("gate")(gate_command)
