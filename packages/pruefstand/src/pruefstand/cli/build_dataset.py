"""``pruefstand build-dataset --config dataset.yaml [--stage S] [--only P] [--resume]`` (T4.7a)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import guarded
from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.pipeline.build_dataset import run_build
from pruefstand.pipeline.build_state import STAGES


def register(app: typer.Typer) -> None:
    """Add the ``build-dataset`` command to ``app``."""

    @app.command("build-dataset")
    def build_dataset_command(
        ctx: typer.Context,
        *,
        config: Annotated[Path, typer.Option("--config", help="dataset.yaml (build settings).")],
        stage: Annotated[
            str | None, typer.Option("--stage", help=f"Run one stage: {', '.join(STAGES)}.")
        ] = None,
        only: Annotated[
            str | None, typer.Option("--only", help="Regenerate one prompt id (generate stage).")
        ] = None,
        resume: Annotated[
            bool, typer.Option("--resume", help="Skip stages that are finished for these inputs.")
        ] = False,
    ) -> None:
        """Build ``datasets/<name>/<version>/`` in six resumable stages.

        The stages are generate, filter, perturb, attacks, splits and validate.

        Relative paths in the config are relative to the current directory. Prints the split counts
        and ``dropped_mixed_license=<n>``; the stage files are in ``work_dir`` (git-ignored).
        """
        with guarded(ctx):
            cfg = load_model(config, DatasetBuildConfig)
            result = asyncio.run(run_build(cfg, stage=stage, only=only, resume=resume))
        if result.manifest is not None:
            counts = " ".join(f"{k.value}={v}" for k, v in result.manifest.splits.items())
            typer.echo(f"splits: {counts}")
            typer.echo(f"wrote {result.directory}")
        else:
            for name, counters in result.report["stages"].items():  # type: ignore[attr-defined]
                typer.echo(f"{name}: {counters}")
        typer.echo(f"dropped_mixed_license={result.report['dropped_mixed_license']}")
