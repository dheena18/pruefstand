"""Commands that later tasks implement; they exit 2 with the owning task (T1.10 S5)."""

import typer

from pruefstand.cli._common import not_implemented

_LENIENT = {"allow_extra_args": True, "ignore_unknown_options": True}


def register(app: typer.Typer) -> None:
    """Add ``build-dataset`` and ``baseline promote`` to ``app``."""

    @app.command("build-dataset", context_settings=_LENIENT)
    def build_dataset_command() -> None:
        """Build a dataset from a corpus (T4.7a)."""
        not_implemented("build-dataset", "T4.7a")

    baseline = typer.Typer(help="Baseline store (T6.1).", no_args_is_help=True)

    @baseline.command("promote", context_settings=_LENIENT)
    def promote_command() -> None:
        """Promote a run to a baseline (T6.1)."""
        not_implemented("baseline promote", "T6.1")

    app.add_typer(baseline, name="baseline")
