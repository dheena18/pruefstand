"""``gate-orchestrator`` (``python -m gate_orchestrator``; T6.2a, D1095): private workflow CLI.

``night-guard`` runs on the hosted guard job and uses only the standard library (this module and
``night_guard`` import nothing else). The other subcommands run on the A40 runner; their handlers
live in ``cmd_*`` modules loaded by name only when chosen, so the guard needs neither pydantic nor
the pruefstand package.
"""

import argparse
import importlib
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from gate_orchestrator.night_guard import GuardError, decide, github_output

Handler = Callable[[argparse.Namespace], int]


def _night_guard(args: argparse.Namespace) -> int:
    try:
        run, deadline = decide(args.event, args.schedule, datetime.now(UTC), args.deadline_input)
    except GuardError as exc:
        sys.stderr.write(f"night-guard: {exc}\n")
        return 2
    sys.stdout.write(github_output(run=run, deadline=deadline))
    return 0


def _lazy(target: str) -> Handler:
    """``"module:function"`` resolved at call time (keeps heavy imports off the hosted guard)."""

    def handler(args: argparse.Namespace) -> int:
        module, name = target.split(":")
        func: Handler = getattr(importlib.import_module(module), name)
        return func(args)

    return handler


def parser() -> argparse.ArgumentParser:
    """The argument parser (one sub-parser per subcommand)."""
    ap = argparse.ArgumentParser(prog="gate-orchestrator", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    guard = sub.add_parser("night-guard", help="decide whether this nightly trigger runs")
    guard.add_argument("--schedule", default="")
    guard.add_argument("--event", required=True)
    guard.add_argument("--deadline-input", default="")
    guard.set_defaults(handler=_night_guard)
    disp = sub.add_parser("dispatch", help="tier 2 for one PR (owner dispatch)")
    disp.add_argument("--pr", type=int, required=True)
    disp.add_argument("--actor", required=True)
    disp.add_argument("--run-id", type=int, required=True)
    disp.add_argument("--report-dir", required=True)
    disp.set_defaults(handler=_lazy("gate_orchestrator.cmd_dispatch:dispatch"))
    promote = sub.add_parser("promote-poll", help="one baseline-promote poll")
    promote.add_argument("--report-dir", required=True)
    promote.set_defaults(handler=_lazy("gate_orchestrator.cmd_promote:promote_poll"))
    backup = sub.add_parser("backup-check", help="laptop backup age into the heartbeat")
    backup.add_argument("--summary", default="")
    backup.set_defaults(handler=_lazy("gate_orchestrator.cmd_backup:backup_check"))
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand; returns its exit code (2 on usage errors)."""
    args = parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args)
