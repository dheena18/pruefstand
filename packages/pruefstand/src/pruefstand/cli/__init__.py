"""Command line interface of Prüfstand (Typer app, entry point ``pruefstand.cli:app``)."""

from importlib.metadata import version as _package_version

import typer

app = typer.Typer(name="pruefstand", no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Prüfstand: release gate for German-language RAG."""


@app.command()
def version() -> None:
    """Print the installed Prüfstand version."""
    typer.echo(f"pruefstand {_package_version('pruefstand')}")
