"""Hardening rules of the private workflow guard (review #214, D1093): rights, tokens, expressions.

Per job: no ``${{`` inside a ``run:`` script (values reach the shell only through ``env:``); the
permissions mapping is exactly ``{contents: read}`` for the hosted ``guard`` and only ``contents``
(``read`` or ``write``) elsewhere; every ``actions/checkout`` sets ``persist-credentials: false``;
no token or secret is expanded on a command line (an ``env:`` value from ``secrets.*``, a token
output or ``github.token`` is never named as ``$NAME`` in a ``run:``); the A40 jobs run on
``[self-hosted, linux, a40]``.
"""

import re

from workflow_model import Doc, steps

RUNNER = ("self-hosted", "linux", "a40")
TOKEN_VALUE = re.compile(r"secrets\s*[.\[]|github\.token|outputs\.token", re.IGNORECASE)
SECRET_ON_LINE = re.compile(r"secrets\s*[.\[]", re.IGNORECASE)


def _map(value: object) -> Doc:
    return value if isinstance(value, dict) else {}


def _env(holder: Doc) -> dict[str, str]:
    return {str(k): str(v) for k, v in _map(holder.get("env")).items()}


def _token_names(doc: Doc, job: Doc, step: Doc) -> set[str]:
    env = {**_env(doc), **_env(job), **_env(step)}
    return {name for name, value in env.items() if TOKEN_VALUE.search(value)}


def _expands(run: str, name: str) -> bool:
    return re.search(rf"\$(\{{)?{re.escape(name)}(?![A-Za-z0-9_])", run) is not None


def _permissions(job_id: str, job: Doc, *, hosted_guard: bool) -> list[str]:
    perms = job.get("permissions")
    if hosted_guard:
        ok = perms == {"contents": "read"}
    else:
        ok = isinstance(perms, dict) and set(perms) == {"contents"}
        ok = ok and _map(perms).get("contents") in {"read", "write"}
    if ok:
        return []
    allowed = "{contents: read}" if hosted_guard else "{contents: read|write}"
    return [f"job {job_id}: permissions must be exactly {allowed}"]


def _step(job_id: str, doc: Doc, job: Doc, step: Doc) -> list[str]:
    out = []
    run = step.get("run")
    if isinstance(run, str):
        if "${{" in run:
            out.append(f"job {job_id}: ${{{{ }}}} inside run: (pass values through env:)")
        if SECRET_ON_LINE.search(run):
            out.append(f"job {job_id}: secrets.* inside run:")
        for name in sorted(_token_names(doc, job, step)):
            if _expands(run, name):
                out.append(f"job {job_id}: token variable ${name} on a command line")
    checkout = str(step.get("uses", "")).startswith("actions/checkout@")
    if checkout and _map(step.get("with")).get("persist-credentials") is not False:
        out.append(f"job {job_id}: checkout without persist-credentials: false")
    return out


def hardening(doc: Doc, job_id: str, job: Doc, *, hosted_guard: bool) -> list[str]:
    """Findings of the review-#214 rules for one job (see the module docstring)."""
    out = _permissions(job_id, job, hosted_guard=hosted_guard)
    runs_on = job.get("runs-on")
    if not hosted_guard and (not isinstance(runs_on, list) or tuple(runs_on) != RUNNER):
        out.append(f"job {job_id}: runs-on must be exactly [self-hosted, linux, a40]")
    for step in steps(job):
        out += _step(job_id, doc, job, step)
    return out
