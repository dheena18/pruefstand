"""``pruefstand judge-drift``: re-judge a judge's anchors and flag drift (T5.4, §15)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import guarded
from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.settings import PruefstandSettings
from pruefstand.judges.anchors import anchor_file
from pruefstand.judges.status import read_status
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of


def register(app: typer.Typer) -> None:
    """Add the ``judge-drift`` command to ``app``."""

    @app.command("judge-drift")
    def judge_drift_command(
        ctx: typer.Context,
        *,
        judge: Annotated[
            str, typer.Option("--judge", help="Judge model id, e.g. ollama/gemma3:12b.")
        ],
        anchors: Annotated[
            Path | None, typer.Option("--anchors", help="Anchor file (default: the shipped one).")
        ] = None,
    ) -> None:
        """Re-judge the anchors, cache bypassed; on drift write judge_drift.json (exit 0)."""
        # scipy-free CLI import (gate review minors): the drift pipeline loads only when run
        from pruefstand.pipeline.judge_drift import run_judge_drift  # noqa: PLC0415

        with guarded(ctx):
            status = read_status()
            threshold = None if status is None else status.drift_thresholds.get(judge)
            a0 = None if status is None else status.self_agreement.get(judge)
            backend = build_backend(
                ModelRef(id=judge, family=family_of(judge)), policy=LLMPolicyConfig()
            )
            result = run_judge_drift(
                judge,
                anchors or anchor_file(judge),
                backend,
                PruefstandSettings().cache_dir,
                threshold=threshold,
                a0=a0,
                now=datetime.now(UTC),
            )
            typer.echo(
                f"judge-drift {judge}: {result.status} n={result.n} agreement={result.agreement} "
                f"changed={result.changed} threshold={result.threshold}"
            )
