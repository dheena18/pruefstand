"""``pruefstand gate``: compare a candidate run with a baseline run."""

from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_FAIL, EXIT_USAGE, fail, guarded, not_implemented
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import GateStatus
from pruefstand.pipeline.gate import GATE_FILE, run_gate

_WARNING = frozenset({GateStatus.WARN, GateStatus.UNSUPPORTED_CONFIG})


def register(app: typer.Typer) -> None:
    """Add the ``gate`` command to ``app``."""

    @app.command("gate")
    def gate_command(
        ctx: typer.Context,
        *,
        candidate: Annotated[Path, typer.Option("--candidate", help="Candidate run directory.")],
        baseline: Annotated[
            Path | None, typer.Option("--baseline", help="Baseline run directory.")
        ] = None,
        from_store: Annotated[
            bool, typer.Option("--from-store", help="Read the baseline from the store (T6.1).")
        ] = False,
        fail_on_warn: Annotated[
            bool, typer.Option("--fail-on-warn", help="Exit 1 on WARN as well.")
        ] = False,
        config: Annotated[
            Path,
            typer.Option(
                "--config",
                envvar="PRUEFSTAND_CONFIG",
                help="Gate policy and seed (the pruefstand.yaml of the run).",
            ),
        ] = Path("pruefstand.yaml"),
    ) -> None:
        """Write ``gate.json`` into the candidate directory; exit 1 on FAIL."""
        if from_store:
            not_implemented("gate --from-store", "T6.1")
        if baseline is None:
            fail("error: give --baseline <run directory> (or --from-store)", EXIT_USAGE)
        if candidate.resolve() == baseline.resolve() or candidate.name == baseline.name:
            fail(
                "error: --candidate and --baseline are the same run; a run cannot gate itself",
                EXIT_USAGE,
            )
        with guarded(ctx):
            report = run_gate(candidate, baseline, load_config(config))
            typer.echo(f"gate {report.status.value}: {candidate / GATE_FILE}")
            failed = report.status is GateStatus.FAIL
            if failed or (fail_on_warn and report.status in _WARNING):
                raise typer.Exit(EXIT_FAIL)
