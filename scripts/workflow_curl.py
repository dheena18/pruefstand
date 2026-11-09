"""Guard rule: every `curl` in a workflow `run:` step retries transient download failures (D926)."""

import re

from workflow_model import Doc, jobs, steps

RETRY_FLAGS = ("--retry 3", "--retry-all-errors", "--retry-delay 5")
_CONTINUATION = re.compile(r"\\\n\s*")
# A curl command word: at line start, after a separator, a shell keyword or `!`, and after
# `VAR=value` assignments; `curl-config`, `curlish` and `echo curl` are not commands.
_CURL = re.compile(
    r"(?:^|[;&|(`]|\b(?:then|do|else|if|elif|while|until|time|sudo|xargs|exec)\b|!)\s*"
    r"(?:[A-Za-z_]\w*=\S*\s+)*curl(?![\w.-])([^\n;&|`)]*)",
    re.MULTILINE,
)


def curl_retries(doc: Doc) -> list[str]:
    """Return findings for `curl` commands in `run:` steps that lack the retry flags.

    Args:
        doc: The parsed workflow.

    Returns:
        One finding per curl command missing any of ``--retry 3``, ``--retry-all-errors`` and
        ``--retry-delay 5`` (a 504 from a release host must not fail a CI job, D926).
    """
    out: list[str] = []
    for job_id, job in jobs(doc).items():
        for step in steps(job):
            run = _CONTINUATION.sub(" ", str(step.get("run", "")))
            for match in _CURL.finditer(run):
                args = " ".join(match.group(1).split())
                missing = [f for f in RETRY_FLAGS if not re.search(rf"(?<!\S){f}(?!\S)", args)]
                if missing:
                    names = ", ".join(missing)
                    out.append(f"job {job_id}: curl lacks {names} (D926)")
    return out
