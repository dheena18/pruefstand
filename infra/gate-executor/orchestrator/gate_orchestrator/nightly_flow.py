"""The nightly job's control flow (N4.3, P2.1, P4.4, A13-M3, D1095, D1099); dependencies injected.

Before the lock: a start at or after the deadline → ``aborted: window_exceeded``;
``MAINTENANCE`` → ``skipped: maintenance``; no signed image on main → ``skipped: preflight ...``.
Under the lock (waited for at most until the phases no longer fit): ``preflight --mode night`` →
``switch-mode.sh night`` → ``judge-drift`` → the gate phase (:class:`NightlyRun`, one infra retry)
→ ``switch-mode.sh day`` in ``finally``. Every outcome sets ``last_nightly_status`` (and
``last_nightly_at`` for ``ok``/``failed``) in the heartbeat, advances the counter only for a
completed night and posts ``pruefstand/nightly`` on main's head.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from gate_orchestrator import heartbeat_store
from gate_orchestrator.dispatch_flow import IMAGE_CONTEXT
from gate_orchestrator.gate_run import Runner, digest_from_status
from gate_orchestrator.github_read import Json, status_of
from gate_orchestrator.heartbeat import nightly_fields
from gate_orchestrator.image import ImageVerificationError
from gate_orchestrator.index_job import Aliases
from gate_orchestrator.infra import InfraError, run_with_retry
from gate_orchestrator.lock import maintenance_path, run_locked
from gate_orchestrator.models import Job
from gate_orchestrator.nightly_run import JUDGE, PLANNED_MINUTES, NightlyRun
from gate_orchestrator.preflight import run_preflight
from gate_orchestrator.state import finish_nightly, nightly_counter_path, read_counter
from gate_orchestrator.status import StatusPoster
from gate_orchestrator.window import late_start, phase_check

STATE = {"ok": "success", "failed": "failure"}
STEP_TIMEOUT_S = 10 * 60
SubprocessRunner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str]]


class MainReader(Protocol):
    """The two public reads of a night (anonymous)."""

    def branch_head(self, branch: str) -> str | None:
        """Head SHA of ``branch``."""

    def statuses(self, sha: str) -> list[Json]:
        """Combined status entries of ``sha``."""


def final_status(status: str) -> tuple[str, str]:
    """``(state, description)`` of ``pruefstand/nightly`` for a ``last_nightly_status`` value."""
    if status == "skipped: maintenance":
        return "success", "skipped: maintenance"
    if status in STATE:
        return STATE[status], f"nightly {status}"
    return "error", f"nightly {status}"


def night_status(result: str) -> str:
    """A13-M3 value for the gate phase's result: ``ok``/``failed``, else a preflight-type skip.

    An infra failure or a refused image is not a completed night (the counter stays, the block
    repeats) and is reported as ``skipped: preflight <reason>`` (D1099).

    >>> night_status("infra error: ollama_down: x")
    'skipped: preflight infra error: ollama_down: x'
    """
    return result if result in STATE else f"skipped: preflight {result}"


def lock_budget_s(now: datetime, deadline: datetime) -> float:
    """How long to wait for the lock: until the phases would no longer fit (>= 0)."""
    phases_total = timedelta(minutes=sum(PLANNED_MINUTES.values()))
    return max(0.0, (deadline - phases_total - now).total_seconds())


def make_runner(deadline: datetime, now: Callable[[], datetime], run: SubprocessRunner) -> Runner:
    """A runner whose ``pruefstand run`` may use all the time left before the deadline.

    The PR runner's 100-minute cap would kill every nightly (review #236); other commands keep
    the 10-minute step timeout.
    """

    def runner(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        if list(argv[:2]) == ["pruefstand", "run"]:
            timeout = max(60.0, (deadline - now()).total_seconds())
        else:
            timeout = float(STEP_TIMEOUT_S)
        return run(argv, env, timeout)

    return runner


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


def _must(run: Runner, argv: list[str], child: dict[str, str]) -> None:
    code, _ = run(argv, child)
    if code != 0:
        msg = f"{Path(argv[0]).name} {argv[1]} exit {code}"
        raise InfraError(msg)


def _gate(attempt: NightlyRun, child: dict[str, str], main_dir: Path) -> None:
    def repair() -> None:
        health = str(main_dir / "infra" / "gpu" / "health.sh")
        _must(attempt.run, ["bash", health, "--repair", "--mode", "night"], child)

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


def locked_night(
    attempt: NightlyRun,
    child: dict[str, str],
    main_dir: Path,
    deadline: datetime,
    now: Callable[[], datetime],
) -> str:
    """The job body under the lock: preflight, phases, ``switch-mode.sh day`` in ``finally``."""
    attempt.env = child
    run = attempt.run
    gpu = main_dir / "infra" / "gpu"
    pre = run_preflight("night", gpu / "health.sh", run, child)
    if not pre.ok:
        return f"skipped: preflight {pre.reason}"
    steps = [
        ("switch-mode", lambda: _must(run, [str(gpu / "switch-mode.sh"), "night"], child)),
        ("judge-drift", lambda: _must(run, ["pruefstand", "judge-drift", "--judge", JUDGE], child)),
        ("nightly-gate", lambda: _gate(attempt, child, main_dir)),
    ]
    try:
        exceeded = phases(now, deadline, steps)
    except InfraError as exc:
        return f"skipped: preflight {exc}"
    finally:
        run([str(gpu / "switch-mode.sh"), "day"], child)
    return "aborted: window_exceeded" if exceeded else night_status(attempt.result)


@dataclass
class NightDeps:
    """Everything a night talks to (the CLI builds the real ones; tests script them)."""

    env: dict[str, str]
    reader: MainReader
    poster: StatusPoster
    run: Runner
    lock_dir: Path
    now: Callable[[], datetime]
    aliases: Aliases | None = None  # the CLI passes qdrant_aliases (D1030)


def _finish(deps: NightDeps, head: str, status: str) -> int:
    now = deps.now()
    path = heartbeat_store.payload_path(deps.env)
    fields = nightly_fields(heartbeat_store.load(path), status, now)
    result = {"ok": "success", "failed": "failure"}.get(status, "skipped")
    heartbeat_store.update(path, {**fields, "last_nightly_result": result}, now)
    finish_nightly(nightly_counter_path(deps.env), status)
    if head:
        deps.poster.post_status(head, *final_status(status))  # type: ignore[arg-type]  # one of the four states
    return 0


def run_nightly(deadline: datetime, report_dir: Path, deps: NightDeps) -> int:
    """One night (see the module docstring); returns 0 (the outcome is in heartbeat and status)."""
    env = deps.env
    main_dir = Path(env["PRUEFSTAND_MAIN_DIR"])
    head = deps.reader.branch_head("main") or ""
    if late_start(deps.now(), deadline):
        return _finish(deps, head, "aborted: window_exceeded")
    if maintenance_path(deps.lock_dir).exists():
        return _finish(deps, head, "skipped: maintenance")
    digest = (
        digest_from_status(status_of(deps.reader.statuses(head), IMAGE_CONTEXT)) if head else None
    )
    if not digest:
        return _finish(deps, head, "skipped: preflight no signed image on main")
    report_dir.mkdir(parents=True, exist_ok=True)
    attempt = NightlyRun(
        job=Job(kind="gate", sha=head, pr_number=None, tier="nightly"),
        digest=digest,
        run=deps.run,
        poster=deps.poster,
        statuses=lambda _sha: [],
        main_config=main_dir / "pruefstand.yaml",
        work=report_dir,
        env=env,
        counter=read_counter(nightly_counter_path(env)),
        runs_dir=Path(env["PRUEFSTAND_HOME"]) / "runs",
        aliases=deps.aliases,
    )
    done = run_locked(
        head,
        lambda child: locked_night(attempt, child, main_dir, deadline, deps.now),
        poster=deps.poster,
        env=env,
        timeout_s=lock_budget_s(deps.now(), deadline),
        lock_dir=deps.lock_dir,
    )
    return _finish(deps, head, done if done is not None else "skipped: runner busy")
