"""Guard rule for ``executor-health.yml`` (T6.2b S8, W2.10, D1092): fixed rights, no secrets."""

import re

from workflow_model import Doc, jobs, strings

EXECUTOR_HEALTH = "executor-health.yml"
EXECUTOR_HEALTH_PERMISSIONS = {"contents": "read", "issues": "write"}
_SECRET = re.compile(r"secrets\s*[.\[]", re.IGNORECASE)


def executor_health(name: str, doc: Doc) -> list[str]:
    """Findings for ``executor-health.yml``.

    Top-level ``{}``, each job exactly ``{contents: read, issues: write}``, no ``secrets.*``.

    Args:
        name: The workflow file name; other workflows yield no findings.
        doc: The parsed workflow.

    Returns:
        One message per violation.
    """
    if name != EXECUTOR_HEALTH:
        return []
    out = [] if doc.get("permissions") == {} else ["top-level permissions must be {}"]
    for job_id, job in jobs(doc).items():
        if job.get("permissions") != EXECUTOR_HEALTH_PERMISSIONS:
            out.append(
                f"job {job_id}: permissions must be exactly {{contents: read, issues: write}}"
            )
    if any(_SECRET.search(s) for s in strings(doc)):
        out.append(
            "no secrets.* in executor-health.yml (it reads the public heartbeat anonymously)"
        )
    return out
