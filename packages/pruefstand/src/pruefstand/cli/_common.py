"""Shared CLI plumbing: the mapping from exceptions to exit codes (interfaces §15).

``0`` pass or warn, ``1`` gate FAIL or ``CorpusMismatch``, ``2`` usage, config or
not-implemented, ``3`` runtime error. Messages go to stderr; a traceback only with ``--verbose``.
"""

import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NoReturn

import typer
from typer.exceptions import TyperException

from pruefstand.core.errors import ConfigError, CorpusMismatch, PruefstandError

EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_RUNTIME = 3


def fail(message: str, code: int) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code``.

    Args:
        message: One line for the user; never a secret.
        code: The exit code.
    """
    typer.echo(message, err=True)
    raise typer.Exit(code)


def not_implemented(what: str, task: str) -> NoReturn:
    """Exit 2 for a command or option that a later task provides.

    Args:
        what: The command or option.
        task: The owning task, e.g. ``"T2.5"``.
    """
    fail(f"{what}: not implemented yet ({task})", EXIT_USAGE)


def _verbose(ctx: typer.Context) -> bool:
    obj = ctx.find_root().obj
    return bool(obj and obj.get("verbose"))


@contextmanager
def guarded(ctx: typer.Context) -> Iterator[None]:
    """Run a command body and turn exceptions into exit codes.

    ``CorpusMismatch`` is 1, ``ConfigError`` 2, any other ``PruefstandError`` 3, and so is any
    unexpected exception (reported by type only, a traceback with ``--verbose``). Typer's own
    exceptions (usage errors, ``Exit``) pass through.

    Args:
        ctx: The command's context (the root context holds the ``--verbose`` flag).

    Raises:
        typer.Exit: With the mapped code.
    """
    try:
        yield
    except (TyperException, typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        code, message = _classify(exc)
        if _verbose(ctx):
            typer.echo(traceback.format_exc(), err=True)
        fail(message, code)


def _classify(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, CorpusMismatch):
        return EXIT_FAIL, f"error: {exc}"
    if isinstance(exc, ConfigError):
        return EXIT_USAGE, f"error: {exc}"
    if isinstance(exc, PruefstandError):
        return EXIT_RUNTIME, f"error: {exc}"
    name = type(exc).__name__
    return EXIT_RUNTIME, f"error: unexpected {name} (run with --verbose for the traceback)"
