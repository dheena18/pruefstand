"""``pruefstand validate config|dataset <path>`` (dataset: ``dataset.validate``, T4.1)."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_USAGE, fail, guarded
from pruefstand.core.config_loader import load_config
from pruefstand.dataset.validate import validate_dataset


class Kind(StrEnum):
    """What ``validate`` checks."""

    CONFIG = "config"
    DATASET = "dataset"


def register(app: typer.Typer) -> None:
    """Add the ``validate`` command to ``app``."""

    @app.command("validate")
    def validate_command(
        ctx: typer.Context,
        kind: Annotated[Kind, typer.Argument(help="config or dataset")],
        path: Annotated[Path, typer.Argument(help="File (config) or directory (dataset).")],
    ) -> None:
        """Check a ``pruefstand.yaml`` or a dataset directory; exit 2 when it is invalid."""
        with guarded(ctx):
            if kind is Kind.CONFIG:
                load_config(path)
                typer.echo(f"ok: {path} is a valid config")
                return
            if str(path).startswith("hf://"):
                fail("error: hf:// datasets arrive in T4.7b", EXIT_USAGE)
            problems = validate_dataset(path)
            if problems:
                for problem in problems:
                    typer.echo(f"error: {problem}", err=True)
                fail(f"FAILED: {len(problems)} problems", EXIT_USAGE)
            typer.echo("OK: 0 problems")
