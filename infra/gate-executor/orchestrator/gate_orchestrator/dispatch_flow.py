"""One owner dispatch of ``gate-executor.yml`` from inputs to statuses (D288, P4.2, D1095).

Order: read the PR, its changed files and statuses → :func:`select_jobs` → for a ``pending`` job
post it (only on change) and record ``pending``; for a ``gate`` job hand it to ``run_gate`` (lock,
preflight, run, result; :mod:`gate_job`). An actor outside ``maintainers.txt`` ends with exit 2 and
no status. A PR without gated paths ends with exit 0 and no status (``gate-router.yml`` owns it).
Pure apart from the injected reader, poster and callables.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from gate_orchestrator.github_read import Json, status_of
from gate_orchestrator.jobs import select_jobs
from gate_orchestrator.models import Dispatch, Job, ProcessedEntry
from gate_orchestrator.report import current_gate_status, post_state
from gate_orchestrator.state import append_processed
from gate_orchestrator.status import StatusPoster

IMAGE_CONTEXT = "pruefstand/image"
MAINTAINERS = Path(__file__).resolve().parent / "maintainers.txt"


class Reader(Protocol):
    """The reads of :class:`gate_orchestrator.github_read.PublicRepo` a dispatch uses."""

    def pull(self, number: int) -> Json:
        """``GET /pulls/{n}``."""

    def files(self, number: int) -> list[str]:
        """Changed paths (old and new path of a rename)."""

    def statuses(self, sha: str) -> list[Json]:
        """Combined status entries of ``sha``."""

    def branch_head(self, branch: str) -> str | None:
        """Head SHA of a branch, or ``None``."""


@dataclass(frozen=True)
class Deps:
    """Everything a dispatch talks to (injected; tests pass real API-shaped data)."""

    reader: Reader
    poster: StatusPoster
    run_gate: Callable[[Job], str]
    processed: Path
    gated_paths: Sequence[str]
    maintainers: frozenset[str]
    now: Callable[[], datetime]


def load_maintainers(path: Path = MAINTAINERS) -> frozenset[str]:
    """Logins allowed to dispatch tier 2 (one per line, ``#`` comments)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(s for line in lines if (s := line.split("#", 1)[0].strip()))


def _record(deps: Deps, dispatch: Dispatch, job: Job, result: str) -> None:
    entry = ProcessedEntry(
        pr=dispatch.pr,
        head_sha=job.sha,
        dispatch_run_id=dispatch.dispatch_run_id,
        result=result,
        run_id="",
        at=deps.now(),
    )
    append_processed(deps.processed, entry)


def _mirror_head(deps: Deps, pr: Json, number: int) -> str | None:
    head_repo = (pr.get("head") or {}).get("repo") or {}
    base_repo = (pr.get("base") or {}).get("repo") or {}
    if head_repo.get("full_name") and head_repo.get("full_name") == base_repo.get("full_name"):
        return None
    return deps.reader.branch_head(f"gate/pr-{number}")


def run_dispatch(dispatch: Dispatch, deps: Deps) -> int:
    """Run one dispatch; returns the process exit code (0).

    Raises:
        ConfigError: the actor is not in ``maintainers.txt`` or the PR data does not match.
        GitHubReadError: a read failed (the job fails; nothing is recorded).
    """
    pr = deps.reader.pull(dispatch.pr)
    files = deps.reader.files(dispatch.pr)
    head = str((pr.get("head") or {}).get("sha", ""))
    image = status_of(deps.reader.statuses(head), IMAGE_CONTEXT) if head else None
    jobs = select_jobs(
        dispatch,
        pr,
        files,
        image,
        deps.gated_paths,
        maintainers=deps.maintainers,
        mirror_head=_mirror_head(deps, pr, dispatch.pr),
    )
    for job in jobs:
        if job.kind == "pending":
            current = current_gate_status(deps.reader.statuses(job.sha))
            post_state(deps.poster, job.sha, "pending", job.reason or "", current)
            _record(deps, dispatch, job, "pending")
        else:
            _record(deps, dispatch, job, deps.run_gate(job))
    return 0
