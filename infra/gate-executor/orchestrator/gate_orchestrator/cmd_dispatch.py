"""``gate-orchestrator dispatch`` (D288, D1095): wire the real reader, poster, runner and paths.

Env: ``PUBLIC_TOKEN`` (the per-job ``pruefstand-bot`` token), ``PRUEFSTAND_MAIN_DIR`` (the trusted
public ``main`` checkout: gate config ``pruefstand.yaml``, ``infra/gpu/health.sh``) and
``PRUEFSTAND_HOME`` (``state/processed.jsonl``). Exit 0 done, 2 refused (actor or PR data).
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from gate_orchestrator.dispatch_flow import IMAGE_CONTEXT, Deps, load_maintainers, run_dispatch
from gate_orchestrator.gate_job import Attempt, run_gate_job
from gate_orchestrator.gate_run import digest_from_status
from gate_orchestrator.github_read import PUBLIC_REPO, PublicRepo, status_of
from gate_orchestrator.index_job import qdrant_aliases
from gate_orchestrator.jobs import load_gated_paths
from gate_orchestrator.models import Dispatch, Job
from gate_orchestrator.post_run import subprocess_runner
from pruefstand.core.errors import ConfigError
from pruefstand.report.github import GitHubPublisher

RUN_TIMEOUT_S = 100 * 60  # one PR run (<= 90 min, D655) plus margin
STEP_TIMEOUT_S = 10 * 60


def runner(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
    """``subprocess_runner`` with the timeout of the command (long for ``pruefstand run``)."""
    timeout = RUN_TIMEOUT_S if list(argv[:2]) == ["pruefstand", "run"] else STEP_TIMEOUT_S
    return subprocess_runner(argv, env, timeout)


def dispatch(args: argparse.Namespace) -> int:
    """The ``dispatch`` subcommand."""
    env = dict(os.environ)
    token = env["PUBLIC_TOKEN"]
    main_dir = Path(env["PRUEFSTAND_MAIN_DIR"])
    reader = PublicRepo(token)
    poster = GitHubPublisher(token, PUBLIC_REPO)
    work = Path(args.report_dir)
    work.mkdir(parents=True, exist_ok=True)

    def run_gate(job: Job) -> str:
        digest = digest_from_status(status_of(reader.statuses(job.sha), IMAGE_CONTEXT)) or ""
        attempt = Attempt(
            job=job,
            digest=digest,
            run=runner,
            poster=poster,
            statuses=reader.statuses,
            main_config=main_dir / "pruefstand.yaml",
            work=work,
            env=env,
            aliases=qdrant_aliases,
        )
        return run_gate_job(attempt, health_sh=main_dir / "infra" / "gpu" / "health.sh")

    deps = Deps(
        reader=reader,
        poster=poster,
        run_gate=run_gate,
        processed=Path(env["PRUEFSTAND_HOME"]) / "state" / "processed.jsonl",
        gated_paths=load_gated_paths(),
        maintainers=load_maintainers(),
        now=lambda: datetime.now(UTC),
    )
    try:
        return run_dispatch(
            Dispatch(pr=args.pr, actor=args.actor, dispatch_run_id=args.run_id), deps
        )
    except ConfigError as exc:
        sys.stderr.write(f"dispatch refused: {exc}\n")
        return 2
