"""``gate-orchestrator promote-poll`` (R9-14, N1.4, D321, D1095): one ``baseline-promote.yml`` poll.

Env: ``PRUEFSTAND_HOME`` (``runs/``, ``state/``), ``PRUEFSTAND_MAIN_DIR`` (trusted main checkout:
gate config, ``infra/gpu/health.sh``). The public repo is read anonymously; nothing is posted to it
(no public token in this workflow): status texts go to the job summary through :class:`LogPoster`.
"""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gate_orchestrator.cmd_dispatch import runner
from gate_orchestrator.cmd_nightly import public_reader
from gate_orchestrator.dispatch_flow import IMAGE_CONTEXT
from gate_orchestrator.gate_job import run_gate_job
from gate_orchestrator.gate_run import Runner, digest_from_status
from gate_orchestrator.github_read import status_of
from gate_orchestrator.models import Job
from gate_orchestrator.nightly import promotable_nightly, prune_due
from gate_orchestrator.nightly_flow import MainReader
from gate_orchestrator.promote import interpret_promote_exit, promotion_commands
from gate_orchestrator.promote_poll import (
    PRUNE_ARGV,
    MainPromotion,
    handled_refs,
    last_prune,
    open_refs,
    read_text,
    record_ref,
    scan_runs,
)
from pruefstand.core.enums import GateStatus

FINAL_MAIN = ("promoted", "not promoted", "integrity error")


@dataclass
class LogPoster:
    """A :class:`StatusPoster` that only collects lines (main runs post no commit status)."""

    lines: list[str] = field(default_factory=list)

    def post_status(self, sha: str, state: str, description: str, context: str = "") -> None:
        """Collect a status line (``context`` is always ``pruefstand/gate`` here)."""
        del context
        self.lines.append(f"{sha[:7]} {state}: {description}")

    def set_check(
        self,
        sha: str,
        status: GateStatus,
        summary: str,
        *,
        no_baseline: bool = False,
        infra_error: bool = False,
    ) -> None:
        """Collect a result line."""
        del no_baseline, infra_error
        self.lines.append(f"{sha[:7]} {status}: {summary}")


@dataclass
class PollDeps:
    """Everything one poll talks to (the CLI builds the real ones; tests script them)."""

    env: dict[str, str]
    reader: MainReader
    run: Runner
    run_job: Callable[[MainPromotion, Path], str]  # run_gate_job(attempt, health_sh=...)
    now: Callable[[], datetime]
    log: LogPoster = field(default_factory=LogPoster)


def _main(deps: PollDeps, state: Path, work: Path) -> None:
    head = deps.reader.branch_head("main")
    if head is None or head == read_text(state / "promote_main_sha"):
        return
    digest = digest_from_status(status_of(deps.reader.statuses(head), IMAGE_CONTEXT))
    if digest is None:
        deps.log.lines.append(f"main {head[:7]}: no signed image yet")
        return
    main_dir = Path(deps.env["PRUEFSTAND_MAIN_DIR"])
    attempt = MainPromotion(
        job=Job(kind="gate", sha=head, pr_number=None, tier="main"),
        digest=digest,
        run=deps.run,
        poster=deps.log,
        statuses=lambda _sha: [],
        main_config=main_dir / "pruefstand.yaml",
        work=work,
        env=deps.env,
    )
    result = deps.run_job(attempt, main_dir / "infra" / "gpu" / "health.sh")
    deps.log.lines.append(f"main {head[:7]}: {result}")
    if result.startswith(FINAL_MAIN):  # busy, maintenance or an infra error: retry next poll
        (state / "promote_main_sha").write_text(head + "\n", encoding="utf-8")


def _nightly(deps: PollDeps, home: Path, state: Path) -> None:
    ledger = state / "promoted_runs.txt"
    handled = handled_refs(ledger)
    runs = scan_runs(home / "runs", handled)
    pick = promotable_nightly([info for info, _ in runs.values()])
    if pick is None:
        return
    run_dir = runs[pick.run_id][1]
    cfg = {
        **deps.env,
        "PRUEFSTAND_CONFIG": str(Path(deps.env["PRUEFSTAND_MAIN_DIR"]) / "pruefstand.yaml"),
    }
    for ref in open_refs(pick, handled):
        commands = promotion_commands(str(run_dir), ref)
        if len(commands) == 2 and deps.run(commands[0], cfg)[0] not in (0, 1):
            deps.log.lines.append(f"gate of {pick.run_id} for {ref} crashed; retried next poll")
            continue
        code, _ = deps.run(commands[-1], cfg)
        outcome = interpret_promote_exit(code, pick.run_id, ref)
        deps.log.lines.append(outcome.summary)
        if outcome.record_processed:
            record_ref(ledger, pick.run_id, ref, outcome.status)


def _prune(deps: PollDeps, state: Path) -> None:
    marker = state / "last_prune"
    now = deps.now()
    if not prune_due(now, last_prune(marker)):
        return
    code, _ = deps.run(PRUNE_ARGV, deps.env)
    deps.log.lines.append(f"baseline prune --keep 20: exit {code}")
    if code == 0:
        marker.write_text(f"{now.year}-{now.month:02d}\n", encoding="utf-8")


def run_poll(deps: PollDeps, work: Path) -> list[str]:
    """One poll: main head, then the newest promotable night, then the monthly prune."""
    home = Path(deps.env["PRUEFSTAND_HOME"])
    state = home / "state"
    state.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    _main(deps, state, work)
    _nightly(deps, home, state)
    _prune(deps, state)
    return deps.log.lines or ["nothing to promote"]


def promote_poll(args: argparse.Namespace) -> int:
    """The ``promote-poll`` subcommand; exit 0 (problems are reported in the summary)."""
    deps = PollDeps(
        env=dict(os.environ),
        reader=public_reader(),
        run=runner,
        run_job=lambda attempt, health: run_gate_job(attempt, health_sh=health),
        now=lambda: datetime.now(UTC),
    )
    sys.stdout.write("\n".join(run_poll(deps, Path(args.report_dir))) + "\n")
    return 0
