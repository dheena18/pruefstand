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
_ENV_FILE = re.compile(
    r"\$\{?(GITHUB_ENV|GITHUB_PATH)\b|\$\{\{\s*github\s*\.\s*(env|path)\s*\}\}", re.I
)
_BARE_GITHUB = re.compile(r"(?<![\w.])github(?![\w.\[-])")
_CONTEXT_REF = re.compile(r"\b(env|matrix)\.([\w-]+)")
_SHELL_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")


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
    {
        "workflow_run",
        "issue_comment",
        "issues",
        "discussion",
        "discussion_comment",
        "pull_request_review",
        "pull_request_review_comment",
    }
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
        if _BARE_GITHUB.search(re.sub(r"'[^']*'", "''", normalised)):  # not in literals
            bad.append("github")  # the whole context, e.g. toJSON(github)
    return bad


def _normalised(code: str) -> list[str]:
    return [BRACKET_NAME.sub(r".\1", e).lower() for e in EXPRESSION.findall(code)]


def _tainted(names: dict[str, object]) -> set[str]:
    """Names (lower case) whose value carries an event value or an untrusted context value."""
    return {
        k.lower()
        for k, v in names.items()
        if any(_bad_event_values(s) or _untrusted(s) for s in strings(v))
    }


def _mapping(node: object) -> dict[str, object]:
    return {str(k): v for k, v in node.items()} if isinstance(node, dict) else {}


def _indirect(code: str, env: set[str], matrix: set[str]) -> list[str]:
    """``${{ env.X }}`` / ``${{ matrix.X }}`` references to a tainted env or matrix value."""
    found = []
    for expression in _normalised(code):
        for kind, name in _CONTEXT_REF.findall(expression):
            if name in (env if kind == "env" else matrix):
                found.append(f"{kind}.{name}")
    return found


def _env_file_writes(run: str, expression_env: set[str]) -> bool:
    """A line that writes GITHUB_ENV/GITHUB_PATH with an expression or an env var set from one."""
    for line in run.splitlines():
        if not _ENV_FILE.search(line):
            continue
        rest = _ENV_FILE.sub("", line)
        if "${{" in rest or any(v.lower() in expression_env for v in _SHELL_VAR.findall(rest)):
            return True
    return False


def _untrusted(code: str) -> bool:
    return any(
        UNTRUSTED.search(BRACKET_NAME.sub(r".\1", e).lower()) for e in EXPRESSION.findall(code)
    )


def _step_findings(
    where: str,
    step: Doc,
    *,
    check_run_untrusted: bool,
    context: tuple[dict[str, object], set[str]] = ({}, set()),
) -> list[str]:
    out = []
    run = step.get("run")
    env_values = {**context[0], **_mapping(step.get("env"))}
    tainted_env, tainted_matrix = _tainted(env_values), context[1]
    expression_env = {k.lower() for k, v in env_values.items() if "${{" in "".join(strings(v))}
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
    for code in [run, *strings(inputs)]:
        if isinstance(code, str):
            out += [
                f"{where}: {ref} carries an untrusted value into run/with (injection)"
                for ref in _indirect(code, tainted_env, tainted_matrix)
            ]
    if check_run_untrusted and isinstance(run, str) and "inputs." in "".join(_normalised(run)):
        out.append(f"{where}: an action input is interpolated in run (pass it through env:)")
    if isinstance(run, str) and _env_file_writes(run, expression_env):
        out.append(
            f"{where}: GITHUB_ENV/GITHUB_PATH is written from an expression or an env var set"
            " from one"
        )
    return out


def event_injection(doc: Doc) -> list[str]:
    """``github.event.*`` values outside ``EVENT_VALUES``, untrusted ``with:`` inputs, env files."""
    out = []
    for job_id, job in jobs(doc).items():
        env = {**_mapping(doc.get("env")), **_mapping(job.get("env"))}
        strategy = _mapping(job.get("strategy"))
        matrix = _tainted(_mapping(strategy.get("matrix")))
        for holder in [job, *steps(job)]:
            out += _step_findings(
                f"job {job_id}", holder, check_run_untrusted=False, context=(env, matrix)
            )
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
