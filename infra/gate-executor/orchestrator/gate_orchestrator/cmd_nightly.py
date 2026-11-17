"""``gate-orchestrator nightly --deadline ISO`` (D1095, D1099): the real dependencies of a night.

The control flow is :mod:`gate_orchestrator.nightly_flow`. Here: the anonymous public reader, the
``pruefstand-bot`` publisher routed to ``pruefstand/nightly``, the subprocess runner whose
``pruefstand run`` may use the time left before the deadline, and the host lock directory.
"""

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gate_orchestrator.github_read import PUBLIC_REPO, PublicRepo
from gate_orchestrator.index_job import qdrant_aliases
from gate_orchestrator.lock import LOCK_DIR
from gate_orchestrator.nightly_flow import NightDeps, make_runner, run_nightly
from gate_orchestrator.post_run import subprocess_runner
from pruefstand.core.enums import GateStatus
from pruefstand.report.github import GitHubPublisher, truncate

CONTEXT = "pruefstand/nightly"


@dataclass
class NightlyPoster:
    """Routes every status of the nightly job to ``pruefstand/nightly`` on main's head."""

    publisher: GitHubPublisher

    def post_status(self, sha: str, state: str, description: str, context: str = "") -> None:
        """Post under ``pruefstand/nightly`` whatever context the caller named."""
        del context
        self.publisher.post_status(sha, state, truncate(description), context=CONTEXT)  # type: ignore[arg-type]  # state is one of the four GitHub states

    def set_check(
        self,
        sha: str,
        status: GateStatus,
        summary: str,
        *,
        no_baseline: bool = False,
        infra_error: bool = False,
    ) -> None:
        """Infra errors of the gate phase (the result itself is posted at the end of the night)."""
        del status, no_baseline
        prefix = "executor infra error: " if infra_error else ""
        self.post_status(sha, "error", f"{prefix}{summary}")


def public_reader() -> PublicRepo:
    """The public repo, read anonymously (no ``Authorization`` header; review #236)."""
    return PublicRepo(None)


def nightly(args: argparse.Namespace) -> int:
    """The ``nightly`` subcommand."""
    env = dict(os.environ)
    deadline = datetime.fromisoformat(args.deadline)

    def now() -> datetime:
        return datetime.now(UTC)

    deps = NightDeps(
        env=env,
        reader=public_reader(),
        poster=NightlyPoster(GitHubPublisher(env["PUBLIC_TOKEN"], PUBLIC_REPO)),
        run=make_runner(deadline, now, subprocess_runner),
        lock_dir=LOCK_DIR,
        now=now,
        aliases=qdrant_aliases,
    )
    return run_nightly(deadline, Path(args.report_dir), deps)
