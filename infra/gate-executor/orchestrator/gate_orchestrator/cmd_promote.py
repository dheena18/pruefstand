"""``gate-orchestrator promote-poll`` (R9-14, N1.4, D321, D1095): one ``baseline-promote.yml`` poll.

Env: ``PRUEFSTAND_HOME`` (``runs/``, ``state/``), ``PRUEFSTAND_MAIN_DIR`` (trusted main checkout:
gate config, ``infra/gpu/health.sh``). The public repo is read anonymously; nothing is posted to it
(no public token in this workflow): status texts go to the job summary through :class:`LogPoster`.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gate_orchestrator.cmd_dispatch import runner
from gate_orchestrator.dispatch_flow import IMAGE_CONTEXT
from gate_orchestrator.gate_job import run_gate_job
from gate_orchestrator.gate_run import digest_from_status
from gate_orchestrator.github_read import PublicRepo, status_of
from gate_orchestrator.models import Job
from gate_orchestrator.nightly import promotable_nightly, promotion_refs, prune_due
from gate_orchestrator.promote import interpret_promote_exit, promotion_commands
from gate_orchestrator.promote_poll import (
    PRUNE_ARGV,
    MainPromotion,
    last_prune,
    promoted_run_ids,
    read_text,
    scan_runs,
)
from pruefstand.core.enums import GateStatus


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


def _main(env: dict[str, str], state: Path, work: Path, log: LogPoster) -> None:
    reader = PublicRepo(None)
    head = reader.branch_head("main")
    if head is None or head == read_text(state / "promote_main_sha"):
        return
    digest = digest_from_status(status_of(reader.statuses(head), IMAGE_CONTEXT))
    if digest is None:
        log.lines.append(f"main {head[:7]}: no signed image yet")
        return
    main_dir = Path(env["PRUEFSTAND_MAIN_DIR"])
    attempt = MainPromotion(
        job=Job(kind="gate", sha=head, pr_number=None, tier="main"),
        digest=digest,
        run=runner,
        poster=log,
        statuses=lambda _sha: [],
        main_config=main_dir / "pruefstand.yaml",
        work=work,
        env=env,
    )
    result = run_gate_job(attempt, health_sh=main_dir / "infra" / "gpu" / "health.sh")
    log.lines.append(f"main {head[:7]}: {result}")
    if result.startswith(("promoted", "not promoted", "integrity error")):
        (state / "promote_main_sha").write_text(head + "\n", encoding="utf-8")


def _nightly(env: dict[str, str], home: Path, state: Path, log: LogPoster) -> None:
    ledger = state / "promoted_runs.txt"
    runs = scan_runs(home / "runs", promoted_run_ids(ledger))
    pick = promotable_nightly([info for info, _ in runs.values()])
    if pick is None:
        return
    run_dir = runs[pick.run_id][1]
    cfg = {**env, "PRUEFSTAND_CONFIG": str(Path(env["PRUEFSTAND_MAIN_DIR"]) / "pruefstand.yaml")}
    for ref in promotion_refs(pick):
        code = 0
        for argv in promotion_commands(str(run_dir), ref):
            code, _ = runner(argv, cfg)
        outcome = interpret_promote_exit(code, pick.run_id, ref)
        log.lines.append(outcome.summary)
        if outcome.record_processed:
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(f"{pick.run_id} {ref} {outcome.status}\n")


def _prune(env: dict[str, str], state: Path, now: datetime, log: LogPoster) -> None:
    marker = state / "last_prune"
    if not prune_due(now, last_prune(marker)):
        return
    code, _ = runner(PRUNE_ARGV, env)
    log.lines.append(f"baseline prune --keep 20: exit {code}")
    if code == 0:
        marker.write_text(f"{now.year}-{now.month:02d}\n", encoding="utf-8")


def promote_poll(args: argparse.Namespace) -> int:
    """The ``promote-poll`` subcommand; exit 0 (problems are reported in the summary)."""
    env = dict(os.environ)
    home = Path(env["PRUEFSTAND_HOME"])
    state = home / "state"
    state.mkdir(parents=True, exist_ok=True)
    work = Path(args.report_dir)
    work.mkdir(parents=True, exist_ok=True)
    log = LogPoster()
    now = datetime.now(UTC)
    _main(env, state, work, log)
    _nightly(env, home, state, log)
    _prune(env, state, now, log)
    sys.stdout.write("\n".join(log.lines or ["nothing to promote"]) + "\n")
    return 0
