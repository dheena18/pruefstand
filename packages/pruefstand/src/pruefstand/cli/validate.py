"""``pruefstand validate config|dataset <path>``."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_USAGE, fail, guarded
from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import DatasetError
from pruefstand.pipeline.datasets import check_dataset


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
            try:
                dataset = check_dataset(str(path))
            except DatasetError as exc:
                fail(f"error: {exc}", EXIT_USAGE)
            typer.echo(f"ok: {path} holds {len(dataset.cases)} valid cases")
