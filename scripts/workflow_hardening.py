"""Hardening rules of the workflow guard (review F3, D1121): permissions, events, composite actions.

Kept apart from ``check_workflows.py`` (file-size limit). The allow-lists are data in
``workflow_policy.py``; each entry carries its reason.
"""

import re
from collections.abc import Iterator

import yaml
from workflow_model import Doc, all_uses, jobs, steps, strings, triggers
from workflow_policy import (
    BRACKET_NAME,
    DANGEROUS_TRIGGERS,
    EVENT_VALUES,
    EXPRESSION,
    OTHER_WRITE,
    UNTRUSTED,
)

SHA_USES = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
DOCKER_USES = re.compile(r"^docker://\S+@sha256:[0-9a-f]{64}$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s#'\"]+)['\"]?\s*(#.*)?$")
VERSION_COMMENT = re.compile(r"#\s*v\d+(\.\d+)*")
# Scopes whose ``write`` grant is checked by a dedicated table in ``check_workflows._grant``.
_OWN_TABLE = frozenset({"contents", "statuses", "id-token", "pages", "models"})
_EVENT_PATH = re.compile(r"github\.event(?![\w-])((?:\.[\w*-]+|\[\s*[\w*]+\s*\])*)")
_ENV_FILE = re.compile(r"\$\{?(GITHUB_ENV|GITHUB_PATH)\b")
_OUTPUT_EXPR = re.compile(r"\b(steps|needs)\.[\w-]+\.outputs\b")


def pins(doc: Doc, text: str) -> list[str]:
    """Findings for ``uses:`` values not pinned to a commit SHA or without a ``# vX.Y.Z``."""
    out = []
    for uses in all_uses(doc):
        local = uses.startswith("./")
        if not (local or SHA_USES.match(uses) or DOCKER_USES.match(uses)):
            out.append(f"uses: {uses} is not pinned to a 40-hex commit SHA")
    for line in text.splitlines():
        match = USES_LINE.match(line)
        if (
            match
            and SHA_USES.match(match.group(1))
            and not VERSION_COMMENT.search(match.group(2) or "")
        ):
            out.append(f"uses: {match.group(1)} lacks a trailing '# vX.Y.Z' comment")
    return out


def _scopes(doc: Doc) -> Iterator[tuple[str | None, object]]:
    yield None, doc.get("permissions")
    for job_id, job in jobs(doc).items():
        yield job_id, job.get("permissions")


def permissions(name: str, doc: Doc) -> list[str]:
    """String permissions (``read-all`` grants actions/models read implicitly) and write scopes.

    Every ``<scope>: write`` without its own table needs an ``OTHER_WRITE`` entry for the job;
    at workflow level such a grant is never allowed.
    """
    out = []
    for job, perms in _scopes(doc):
        where = f"job {job}" if job else "workflow level"
        if isinstance(perms, str):
            out.append(f"{where}: permissions '{perms}' as a string is forbidden (use a mapping)")
        if not isinstance(perms, dict):
            continue
        for key, level in perms.items():
            scope = str(key)
            if str(level) != "write" or scope in _OWN_TABLE:
                continue
            if job is None or (name, job, scope) not in OTHER_WRITE:
                out.append(f"{where}: '{scope}: write' is not on the allow-list for {name}")
    return out


_TRIGGER_NAMES = frozenset(
    {"workflow_run", "issue_comment", "pull_request_review", "pull_request_review_comment"}
)


def dangerous_triggers(name: str, doc: Doc) -> list[str]:
    """Base-repo-rights triggers on attacker input need a ``DANGEROUS_TRIGGERS`` entry."""
    found = {str(t) for t in triggers(doc)} & _TRIGGER_NAMES
    return [
        f"trigger {t} is not on the allow-list for {name}"
        for t in sorted(found)
        if (name, t) not in DANGEROUS_TRIGGERS
    ]


def _bad_event_values(code: str) -> list[str]:
    bad = []
    for expression in EXPRESSION.findall(code):
        normalised = BRACKET_NAME.sub(r".\1", expression).lower()
        for match in _EVENT_PATH.finditer(normalised):
            path = "github.event" + re.sub(r"\s+", "", match.group(1))
            if EVENT_VALUES.fullmatch(path) is None:
                bad.append(path)
    return bad


def _untrusted(code: str) -> bool:
    return any(
        UNTRUSTED.search(BRACKET_NAME.sub(r".\1", e).lower()) for e in EXPRESSION.findall(code)
    )


def _step_findings(where: str, step: Doc, *, check_run_untrusted: bool) -> list[str]:
    out = []
    run = step.get("run")
    with_ = step.get("with")
    inputs = dict(with_) if isinstance(with_, dict) else {}
    for code in [run, *strings(inputs)]:
        if isinstance(code, str):
            out += [
                f"{where}: {p} interpolated in run/with is not on the allow-list (injection)"
                for p in _bad_event_values(code)
            ]
    others = [v for k, v in inputs.items() if k != "script"]
    if any(_untrusted(c) for c in strings(others)) or (
        check_run_untrusted and isinstance(run, str) and _untrusted(run)
    ):
        out.append(f"{where}: untrusted value interpolated in run/with input (injection)")
    if (
        isinstance(run, str)
        and _ENV_FILE.search(run)
        and any(_OUTPUT_EXPR.search(e) for e in EXPRESSION.findall(run))
    ):
        out.append(f"{where}: a step output is interpolated into GITHUB_ENV/GITHUB_PATH")
    return out


def event_injection(doc: Doc) -> list[str]:
    """``github.event.*`` values outside ``EVENT_VALUES``, untrusted ``with:`` inputs, env files."""
    out = []
    for job_id, job in jobs(doc).items():
        holders = [job, *steps(job)]
        for holder in holders:
            out += _step_findings(f"job {job_id}", holder, check_run_untrusted=False)
    return out


def hardening(name: str, doc: Doc) -> list[str]:
    """All review-F3 rules of one workflow."""
    return [*permissions(name, doc), *dangerous_triggers(name, doc), *event_injection(doc)]


def check_action_text(name: str, text: str) -> list[str]:
    """Check one composite action (``.github/actions/*/action.yml``): pins and injection.

    Args:
        name: Display name, e.g. ``live-stack/action.yml``.
        text: The action's YAML source.

    Returns:
        Findings as ``"<name>: <message>"``.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{name}: invalid YAML: {exc}"]
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if not isinstance(runs, dict):
        return [f"{name}: invalid action: no runs: mapping"]
    as_job: Doc = {"jobs": {"composite": {"steps": runs.get("steps", [])}}}
    out = pins(as_job, text)
    for step in steps(jobs(as_job)["composite"]):
        out += _step_findings("composite", step, check_run_untrusted=True)
    return [f"{name}: {message}" for message in out]
