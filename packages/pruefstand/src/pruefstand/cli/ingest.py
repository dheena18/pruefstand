"""``pruefstand ingest --config corpus.yaml --out corpus/ [--date YYYY-MM-DD]`` (T2.5)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import guarded
from pruefstand.pipeline.ingest import build_corpus


def register(app: typer.Typer) -> None:
    """Add the ``ingest`` command to ``app``."""

    @app.command("ingest")
    def ingest_command(
        ctx: typer.Context,
        *,
        config: Annotated[Path, typer.Option("--config", help="corpus.yaml (tenant plan).")],
        out: Annotated[Path, typer.Option("--out", help="Parent of the corpus versions.")] = Path(
            "corpus"
        ),
        date_tag: Annotated[
            str | None,
            typer.Option("--date", help="Build date YYYY-MM-DD (default: today, UTC)."),
        ] = None,
    ) -> None:
        """Build ``corpus/<corpus_version>/`` (one chunk file per tenant plus manifest.json)."""
        with guarded(ctx):
            day = date_tag or datetime.now(UTC).date().isoformat()
            manifest = build_corpus(config, out, day)
        typer.echo(f"corpus_version={manifest.corpus_version}")
        for tenant, count in manifest.tenants.items():
            typer.echo(f"{tenant}: {count}")
        typer.echo(f"wrote {out / manifest.corpus_version}")
