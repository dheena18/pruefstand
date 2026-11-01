"""Guard for jobs that hold a write token and must run no repository code (cassettes.yml `push`)."""

from workflow_model import Doc, jobs, steps
from workflow_policy import NO_REPO_CODE_ACTIONS, NO_REPO_CODE_JOBS, REPO_CODE_RUN


def no_repo_code(name: str, doc: Doc) -> list[str]:
    """Return findings for write-token jobs that run repository code or hold extra rights."""
    out: list[str] = []
    for job_id, job in jobs(doc).items():
        allowed = NO_REPO_CODE_JOBS.get((name, job_id))
        if allowed is None:
            continue
        if job.get("permissions") != allowed:
            out.append(f"job {job_id}: permissions must be exactly {allowed} (holds a write token)")
        for step in steps(job):
            if REPO_CODE_RUN.search(str(step.get("run", ""))):
                out.append(f"job {job_id}: a step runs repository code (uv/make/python/scripts)")
            uses = str(step.get("uses", ""))
            if uses and not uses.startswith(NO_REPO_CODE_ACTIONS):
                action = uses.split("@", maxsplit=1)[0]
                out.append(f"job {job_id}: action {action} is not allowed in this job")
    return out
