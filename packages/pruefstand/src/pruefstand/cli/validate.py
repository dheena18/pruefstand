"""``pruefstand validate config|dataset <path>`` (dataset: ``dataset.validate``, T4.1)."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_USAGE, fail, guarded
from pruefstand.core.config_loader import load_config
from pruefstand.dataset.validate import validate_dataset
from pruefstand.pipeline.datasets_hf import resolve_hf


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
        path: Annotated[
            str, typer.Argument(help="File (config), directory or hf:// reference (dataset).")
        ],
    ) -> None:
        """Check a ``pruefstand.yaml`` or a dataset directory; exit 2 when it is invalid."""
        with guarded(ctx):
            if kind is Kind.CONFIG:
                load_config(Path(path))
                typer.echo(f"ok: {path} is a valid config")
                return
            target = resolve_hf(path) if path.startswith("hf://") else Path(path)
            problems = validate_dataset(target)
            if problems:
                for problem in problems:
                    typer.echo(f"error: {problem}", err=True)
                fail(f"FAILED: {len(problems)} problems", EXIT_USAGE)
            typer.echo("OK: 0 problems")
