"""``pruefstand run``: evaluate a target and write a run directory."""

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_RUNTIME, fail, guarded
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import Split
from pruefstand.core.models.run import RunResults
from pruefstand.pipeline.run import run_eval
from pruefstand.pipeline.select import resolve_block


class TierOption(StrEnum):
    """``--tier``."""

    PR = "pr"
    NIGHTLY = "nightly"
    BENCH = "bench"


class StratumOption(StrEnum):
    """``--stratum``."""

    ALL = "all"
    REFUSAL = "refusal"
    BLOCKS = "blocks"


def _splits(names: list[str]) -> tuple[Split, ...]:
    try:
        return tuple(dict.fromkeys(Split(name) for name in names))
    except ValueError:
        known = ", ".join(s.value for s in Split)
        msg = f"--split must be one of: {known}"
        raise typer.BadParameter(msg) from None


def _finish(out: Path, results: RunResults) -> None:
    manifest = results.manifest
    typer.echo(str(out / manifest.run_id))
    if not manifest.complete:
        fail(f"run stopped early: stop_reason={manifest.stop_reason}", EXIT_RUNTIME)


def register(app: typer.Typer) -> None:
    """Add the ``run`` command to ``app``."""

    @app.command("run")
    def run_command(
        ctx: typer.Context,
        *,
        config: Annotated[Path, typer.Option("--config", help="pruefstand.yaml")],
        tier: Annotated[TierOption, typer.Option("--tier", help="pr, nightly or bench")],
        out: Annotated[Path, typer.Option("--out", help="Directory for run directories.")],
        split: Annotated[
            list[str] | None, typer.Option("--split", help="Replaces the configured splits.")
        ] = None,
        stratum: Annotated[
            StratumOption, typer.Option("--stratum", help="Case selector inside full.")
        ] = StratumOption.ALL,
        block: Annotated[
            str | None, typer.Option("--block", help="auto, 0, 1 or 2 (needs --split full).")
        ] = None,
        judged_subset: Annotated[
            bool, typer.Option("--judged-subset", help="Judge and generate the subset only.")
        ] = False,
    ) -> None:
        """Evaluate the configured target and print the run directory."""
        with guarded(ctx):
            cfg = load_config(config)
            if split:
                cfg = cfg.model_copy(update={"splits": _splits(split)})
            results = asyncio.run(
                run_eval(
                    cfg,
                    tier=tier.value,
                    out=out,
                    block=resolve_block(block),
                    judged_subset=judged_subset,
                    stratum=stratum.value,
                )
            )
            _finish(out, results)
