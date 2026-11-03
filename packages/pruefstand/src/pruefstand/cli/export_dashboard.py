"""``pruefstand export-dashboard``: run directories to the published dashboard data tree (T8.1)."""

from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import guarded
from pruefstand.report.dashboard_export import export_dashboard
from pruefstand.store.canary_source import load_canary_registry


def export_dashboard_command(
    ctx: typer.Context,
    *,
    runs: Annotated[Path, typer.Option("--runs", help="Directory with run directories.")],
    out: Annotated[Path, typer.Option("--out", help="New output directory (the data tree).")],
) -> None:
    """Sanitise the runs and write the dashboard data tree (index, cases, report.html, labels)."""
    with guarded(ctx):
        index = export_dashboard(runs, out, load_canary_registry())
        typer.echo(f"exported {len(index.runs)} runs to {out}")


def register(app: typer.Typer) -> None:
    """Add the ``export-dashboard`` command to ``app``."""
    app.command("export-dashboard")(export_dashboard_command)
