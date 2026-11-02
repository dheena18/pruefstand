"""Command line interface of Prüfstand (Typer app, entry point ``pruefstand.cli:app``).

One module per command; each exposes ``register(app)``. The commands only parse arguments and map
exceptions to exit codes; the work is done in ``pruefstand.pipeline``.
"""

from importlib.metadata import version as _package_version
from typing import Annotated

import typer
from pydantic import ValidationError

from pruefstand.cli import gate as _gate
from pruefstand.cli import ingest as _ingest
from pruefstand.cli import power as _power
from pruefstand.cli import report as _report
from pruefstand.cli import run as _run
from pruefstand.cli import schema as _schema
from pruefstand.cli import stubs as _stubs
from pruefstand.cli import validate as _validate
from pruefstand.cli._common import EXIT_USAGE, fail
from pruefstand.core.logging import configure_logging
from pruefstand.core.settings import PruefstandSettings

app = typer.Typer(name="pruefstand", no_args_is_help=True, add_completion=False)


@app.callback()
def main(
    ctx: typer.Context,
    *,
    log_json: Annotated[
        bool | None,
        typer.Option("--log-json/--no-log-json", help="JSON log lines (default: on in CI)."),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Debug logging and tracebacks.")
    ] = False,
) -> None:
    """Prüfstand: release gate for German-language RAG."""
    ctx.obj = {"verbose": verbose}
    try:
        use_json = PruefstandSettings().log_json if log_json is None else log_json
    except ValidationError:
        fail("error: an environment variable PRUEFSTAND_* is invalid", EXIT_USAGE)
    configure_logging(json=use_json, level="DEBUG" if verbose else "INFO")


@app.command()
def version() -> None:
    """Print the installed Prüfstand version."""
    typer.echo(f"pruefstand {_package_version('pruefstand')}")


for _module in (_run, _gate, _report, _validate, _schema, _power, _ingest, _stubs):
    _module.register(app)
