"""``pruefstand schema export``: JSON Schemas of the persisted models."""

from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import guarded
from pruefstand.core.schema import export_schemas


def register(app: typer.Typer) -> None:
    """Add the ``schema`` command group to ``app``."""
    group = typer.Typer(help="JSON Schemas of the persisted models.", no_args_is_help=True)

    @group.command("export")
    def export_command(
        ctx: typer.Context,
        out: Annotated[Path, typer.Option("--out", help="Target directory.")],
    ) -> None:
        """Write one ``<name>.schema.json`` per registered model into ``--out``."""
        with guarded(ctx):
            paths = export_schemas(out)
        typer.echo(f"wrote {len(paths)} schemas to {out}")

    app.add_typer(group, name="schema")
