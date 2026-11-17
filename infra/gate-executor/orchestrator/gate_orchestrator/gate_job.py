"""A ``gate`` job of a dispatch (X2.1, Y5.2, D226, D1095): lock, preflight, attempt, retry once.

``run_gate_job`` returns the ``processed.jsonl`` result: ``busy`` / ``maintenance`` (no lock, a
``pending`` status is posted), ``error`` (preflight failed, or the second infra failure), or the
gate status of the completed attempt. One attempt (:meth:`Attempt.__call__`): image → candidate →
``pruefstand run`` → ``pruefstand gate`` → result status (only on change); the candidate container
is removed in every case.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from gate_orchestrator.candidate import candidate_argv
from gate_orchestrator.gate_run import (
    CANDIDATE_PORT,
    Runner,
    candidate_env,
    gate_argv,
    ip_argv,
    pruefstand_run_argv,
    read_outcome,
    run_config,
)
from gate_orchestrator.image import ImageVerificationError, verify_image
from gate_orchestrator.infra import InfraError, run_with_retry
from gate_orchestrator.lock import LOCK_DIR, run_locked
from gate_orchestrator.models import Job
from gate_orchestrator.preflight import report_preflight, run_preflight
from gate_orchestrator.report import current_gate_status, post_gate_result
from gate_orchestrator.status import StatusPoster
from pruefstand.core.enums import GateStatus
from pruefstand.report.github import truncate

LOCK_TIMEOUT_S = 2 * 3600  # PR and promote jobs wait at most 2 h (A12-M1)


@dataclass
class Attempt:
    """One gate attempt with everything injected (runner, paths, poster, statuses reader)."""

    job: Job
    digest: str
    run: Runner
    poster: StatusPoster
    statuses: Callable[[str], list[dict[str, object]]]
    main_config: Path
    work: Path
    env: Mapping[str, str] = field(default_factory=dict)
    judged_subset: bool = False
    result: str = "error"

    def _must(self, argv: list[str], what: str) -> str:
        code, out = self.run(argv, self.env)
        if code != 0:
            msg = f"candidate_down: {what} exit {code}"
            raise InfraError(msg)
        return out

    def _run_and_gate(self, url: str) -> str | None:
        config = run_config(self.main_config, self.work / "pruefstand.yaml", url)
        runs = self.work / "runs"
        argv = pruefstand_run_argv(config, runs, judged_subset=self.judged_subset)
        code, out = self.run(argv, self.env)
        lines = out.strip().splitlines()
        if code != 0 or not lines:
            msg = f"run_failed: pruefstand run exit {code}"
            raise InfraError(msg)
        run_dir = Path(lines[-1])
        self.run(gate_argv(run_dir, config), self.env)  # exit 1 on FAIL is a result, not an error
        outcome = read_outcome(run_dir)
        if outcome.infra_error:
            return outcome.infra_error
        current = current_gate_status(self.statuses(self.job.sha))
        post_gate_result(
            self.poster,
            self.job.sha,
            status=GateStatus(outcome.status),
            summary=outcome.summary,
            no_baseline=outcome.no_baseline,
            current=current,
        )
        self.result = outcome.status
        return None

    def __call__(self, number: int) -> str | None:
        """Run attempt ``number``; returns the run's ``infra_error`` or ``None`` (result posted)."""
        name = f"candidate-{self.job.pr_number}-{self.job.sha[:7]}-{number}"
        self._must(
            ["docker", "pull", "--quiet", f"ghcr.io/dheena18/rag-demo@{self.digest}"], "pull"
        )
        ref = verify_image(self.digest, self.job.sha, lambda argv: self.run(argv, self.env))
        cenv = candidate_env(self.env)
        argv = candidate_argv(ref, name=name, job_label=name, env=cenv)
        try:
            self._must(argv, "docker run")
            ip = self._must(ip_argv(name), "inspect").strip()
            return self._run_and_gate(f"http://{ip}:{CANDIDATE_PORT}")
        finally:
            self.run(["docker", "rm", "-f", name], self.env)


def run_gate_job(
    attempt: Attempt,
    *,
    health_sh: Path,
    lock_dir: Path | None = None,
) -> str:
    """Lock → preflight → attempt (one infra retry after ``health.sh --repair``).

    Returns:
        The ``processed.jsonl`` result text.
    """
    sha = attempt.job.sha

    def body(child: dict[str, str]) -> str:
        attempt.env = child
        pre = run_preflight("day", health_sh, attempt.run, child)
        if not report_preflight(sha, pre, attempt.poster):
            return "error"

        def repair() -> None:
            code, _ = attempt.run([str(health_sh), "--repair", "--mode", "day"], child)
            if code != 0:
                msg = f"repair_failed: health.sh exit {code}"
                raise InfraError(msg)

        def record_error(text: str) -> None:
            attempt.result = f"error: {text}"

        try:
            run_with_retry(
                sha, attempt, repair=repair, poster=attempt.poster, record_error=record_error
            )
        except ImageVerificationError as exc:  # the origin check failed: never run the image
            attempt.poster.post_status(sha, "error", truncate(str(exc)))
            attempt.result = f"error: {exc}"
        return attempt.result

    done = run_locked(
        sha,
        body,
        poster=attempt.poster,
        env=attempt.env,
        timeout_s=LOCK_TIMEOUT_S,
        lock_dir=LOCK_DIR if lock_dir is None else lock_dir,
    )
    return done if done is not None else "not run (maintenance or busy)"
