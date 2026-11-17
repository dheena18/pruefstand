"""``gate-orchestrator nightly --deadline ISO`` (N4.3, P2.1, P4.4, A13-M3, D1095, D1099).

Before the lock: a start at or after the deadline → ``aborted: window_exceeded``;
``MAINTENANCE`` → ``skipped: maintenance``; no signed image on main → ``skipped: preflight ...``.
Under the lock (waited for at most until the gate phase no longer fits): ``preflight --mode night``
→ ``switch-mode.sh night`` → ``judge-drift`` → the gate phase (:class:`NightlyRun`, one infra
retry) → ``switch-mode.sh day`` in ``finally``. Every outcome sets ``last_nightly_status`` (and
``last_nightly_at`` for ``ok``/``failed``) in the heartbeat, advances the counter only for a
completed night and posts ``pruefstand/nightly`` on main's head. Env as for ``dispatch``.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gate_orchestrator import heartbeat_store
from gate_orchestrator.cmd_dispatch import runner
from gate_orchestrator.dispatch_flow import IMAGE_CONTEXT
from gate_orchestrator.gate_run import digest_from_status
from gate_orchestrator.github_read import PUBLIC_REPO, PublicRepo, status_of
from gate_orchestrator.heartbeat import nightly_fields
from gate_orchestrator.image import ImageVerificationError
from gate_orchestrator.infra import InfraError, run_with_retry
from gate_orchestrator.lock import LOCK_DIR, maintenance_path, run_locked
from gate_orchestrator.models import Job
from gate_orchestrator.nightly_probe import probe_argv
from gate_orchestrator.nightly_run import JUDGE, PLANNED_MINUTES, NightlyRun
from gate_orchestrator.preflight import run_preflight
from gate_orchestrator.state import finish_nightly, nightly_counter_path, read_counter
from gate_orchestrator.window import late_start, phase_check
from pruefstand.core.enums import GateStatus
from pruefstand.report.github import GitHubPublisher, truncate

CONTEXT = "pruefstand/nightly"
STATE = {"ok": "success", "failed": "failure"}


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
        """Infra errors of the gate phase (the result itself is posted by :func:`final_status`)."""
        del status, no_baseline
        prefix = "executor infra error: " if infra_error else ""
        self.post_status(sha, "error", f"{prefix}{summary}")


def final_status(status: str) -> tuple[str, str]:
    """``(state, description)`` of ``pruefstand/nightly`` for a ``last_nightly_status`` value."""
    if status == "skipped: maintenance":
        return "success", "skipped: maintenance"
    if status in STATE:
        return STATE[status], f"nightly {status}"
    return "error", f"nightly {status}"


def lock_budget_s(now: datetime, deadline: datetime) -> float:
    """How long to wait for the lock: until the gate phase would no longer fit (>= 0)."""
    gate = timedelta(minutes=sum(PLANNED_MINUTES.values()))
    return max(0.0, (deadline - gate - now).total_seconds())


def phases(
    now: Callable[[], datetime], deadline: datetime, steps: Sequence[tuple[str, Callable[[], None]]]
) -> str | None:
    """Run ``(phase, step)`` in order; ``window_exceeded: <phase>`` when one no longer fits."""
    for name, step in steps:
        exceeded = phase_check(now(), deadline, name, PLANNED_MINUTES[name])
        if exceeded:
            return exceeded
        step()
    return None


def _finish(env: dict[str, str], status: str, post: Callable[[str, str], None]) -> int:
    now = datetime.now(UTC)
    path = heartbeat_store.payload_path(env)
    fields = nightly_fields(heartbeat_store.load(path), status, now)
    result = {"ok": "success", "failed": "failure"}.get(status, "skipped")
    heartbeat_store.update(path, {**fields, "last_nightly_result": result}, now)
    finish_nightly(nightly_counter_path(env), status)
    post(*final_status(status))
    return 0


def _must(argv: list[str], child: dict[str, str]) -> None:
    code, _ = runner(argv, child)
    if code != 0:
        msg = f"{Path(argv[0]).name} {argv[1]} exit {code}"
        raise InfraError(msg)


def _inform(build: Callable[[], list[str]], child: dict[str, str]) -> None:
    """An informational phase: reported, never fails the night (T4.6 S7)."""
    try:
        argv = build()
    except (OSError, ValueError) as exc:
        sys.stdout.write(f"informational phase not run: {exc}\n")
        return
    code, _ = runner(argv, child)
    sys.stdout.write(f"{Path(argv[1]).name}: exit {code} (informational)\n")


def locked_night(
    attempt: NightlyRun, child: dict[str, str], main_dir: Path, deadline: datetime
) -> str:
    """The job body under the lock: preflight, phases, ``switch-mode.sh day`` in ``finally``."""
    attempt.env = child
    gpu = main_dir / "infra" / "gpu"
    pre = run_preflight("night", gpu / "health.sh", runner, child)
    if not pre.ok:
        return f"skipped: preflight {pre.reason}"
    steps = [
        ("switch-mode", lambda: _must([str(gpu / "switch-mode.sh"), "night"], child)),
        ("judge-drift", lambda: _must(["pruefstand", "judge-drift", "--judge", JUDGE], child)),
        ("nightly-gate", lambda: _gate(attempt, child, main_dir)),
        ("contamination-probe", lambda: _inform(lambda: probe_argv(main_dir, attempt.work), child)),
    ]
    try:
        exceeded = phases(lambda: datetime.now(UTC), deadline, steps)
    except InfraError as exc:
        return f"skipped: preflight {exc}"
    finally:
        runner([str(gpu / "switch-mode.sh"), "day"], child)
    return "aborted: window_exceeded" if exceeded else night_status(attempt.result)


def nightly(args: argparse.Namespace) -> int:
    """The ``nightly`` subcommand (see the module docstring)."""
    env = dict(os.environ)
    deadline = datetime.fromisoformat(args.deadline)
    main_dir = Path(env["PRUEFSTAND_MAIN_DIR"])
    reader = PublicRepo(None)
    head = reader.branch_head("main") or ""
    poster = NightlyPoster(GitHubPublisher(env["PUBLIC_TOKEN"], PUBLIC_REPO))

    def post(state: str, description: str) -> None:
        if head:
            poster.post_status(head, state, description)

    if late_start(datetime.now(UTC), deadline):
        return _finish(env, "aborted: window_exceeded", post)
    if maintenance_path(LOCK_DIR).exists():
        return _finish(env, "skipped: maintenance", post)
    digest = digest_from_status(status_of(reader.statuses(head), IMAGE_CONTEXT)) if head else None
    if not digest:
        return _finish(env, "skipped: preflight no signed image on main", post)
    work = Path(args.report_dir)
    work.mkdir(parents=True, exist_ok=True)
    attempt = NightlyRun(
        job=Job(kind="gate", sha=head, pr_number=None, tier="nightly"),
        digest=digest,
        run=runner,
        poster=poster,
        statuses=lambda _sha: [],
        main_config=main_dir / "pruefstand.yaml",
        work=work,
        env=env,
        counter=read_counter(nightly_counter_path(env)),
    )
    budget = lock_budget_s(datetime.now(UTC), deadline)
    done = run_locked(
        head,
        lambda child: locked_night(attempt, child, main_dir, deadline),
        poster=poster,
        env=env,
        timeout_s=budget,
    )
    return _finish(env, done if done is not None else "skipped: runner busy", post)


def night_status(result: str) -> str:
    """A13-M3 value for the gate phase's result: ``ok``/``failed``, else a preflight-type skip.

    An infra failure or a refused image is not a completed night (the counter stays, the block
    repeats) and is reported as ``skipped: preflight <reason>`` (D1099).

    >>> night_status("infra error: ollama_down: x")
    'skipped: preflight infra error: ollama_down: x'
    """
    return result if result in STATE else f"skipped: preflight {result}"


def _gate(attempt: NightlyRun, child: dict[str, str], main_dir: Path) -> None:
    def repair() -> None:
        health = str(main_dir / "infra" / "gpu" / "health.sh")
        runner([health, "--repair", "--mode", "night"], child)

    def record_error(text: str) -> None:
        attempt.result = f"infra error: {text}"

    try:
        run_with_retry(
            attempt.job.sha,
            attempt,
            repair=repair,
            poster=attempt.poster,
            record_error=record_error,
        )
    except ImageVerificationError as exc:
        attempt.result = str(exc)
