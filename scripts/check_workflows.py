"""Workflow guard for the public repo (T0.2 S3, S3d): fails on unsafe GitHub Actions workflows.

Usage: ``python scripts/check_workflows.py [.github/workflows]``. Prints ``ok: N workflows checked``
and exits 0, or prints one finding per line (``<file>: <message>``) and exits 1. The rules and the
allow-lists (``workflow_policy.py``) are documented in ``docs/engineering/ci-cd.md`` §1.
"""

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import yaml
from workflow_model import Doc, all_uses, environment, jobs, steps, strings, triggers
from workflow_policy import (
    ACTIONS_READ,
    APP_TOKEN_ACTION,
    BRACKET_NAME,
    BUILD_IMAGES,
    BUILD_IMAGES_REF,
    CONTENTS_WRITE,
    EXPRESSION,
    FETCH_PR_CODE,
    GATE_ROUTER,
    GATE_ROUTER_ENV,
    GATE_ROUTER_SECRETS,
    ID_TOKEN_WRITE,
    MODELS_READ_FILES,
    PAGES_WRITE,
    STATUSES_WRITE,
    UNTRUSTED,
)

SHA_USES = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
DOCKER_USES = re.compile(r"^docker://\S+@sha256:[0-9a-f]{64}$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s#'\"]+)['\"]?\s*(#.*)?$")
VERSION_COMMENT = re.compile(r"#\s*v\d+(\.\d+)*")
SECRET_REF = re.compile(r"secrets(?:\s*\.\s*|\s*\[\s*['\"])(\w+)", re.IGNORECASE)


def _pins(doc: Doc, text: str) -> list[str]:
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


def _crons(doc: Doc) -> list[str]:
    schedule = triggers(doc).get("schedule")
    out = []
    for entry in schedule if isinstance(schedule, list) else []:
        cron = str(entry.get("cron", "")) if isinstance(entry, dict) else ""
        field = cron.split()[0] if cron.split() else ""
        if any(_busy_minute(part) for part in field.split(",")):
            out.append(f"schedule '{cron}': off-minute crons only (minute 0, * or */N)")
    return out


def _busy_minute(part: str) -> bool:
    """True for `*`, `*/N` and any range, list item or step starting at minute 0."""
    start = part.split("/", maxsplit=1)[0].split("-", maxsplit=1)[0]
    return start.startswith("*") or (start.isdigit() and int(start) == 0)


def _self_hosted(job: Doc) -> bool:
    runs_on = "\n".join(strings(job.get("runs-on", "")))
    if "${{" in runs_on:  # e.g. ${{ matrix.os }}: look at every value the matrix could take
        runs_on += "\n" + "\n".join(strings(job.get("strategy", "")))
    return "self-hosted" in runs_on.lower()


def _triggers_and_runners(name: str, doc: Doc) -> list[str]:
    out = []
    if "pull_request_target" in triggers(doc) and name != GATE_ROUTER:
        out.append(f"pull_request_target is allowed only in {GATE_ROUTER}")
    out += _crons(doc)
    for job_id, job in jobs(doc).items():
        if _self_hosted(job):
            out.append(f"job {job_id}: runs-on self-hosted is forbidden in the public repo")
    return out


def _perm_scopes(doc: Doc) -> Iterator[tuple[str | None, object]]:
    yield None, doc.get("permissions")
    for job_id, job in jobs(doc).items():
        yield job_id, job.get("permissions")


def _grant(name: str, job: str | None, key: str, level: str) -> str | None:
    where = f"job {job}" if job else "workflow level"
    if key == "models" and (
        level == "write" or (level == "read" and name not in MODELS_READ_FILES)
    ):
        return f"{where}: 'models: {level}' is not allowed in {name}"
    table = {
        "actions": ACTIONS_READ,
        "contents": CONTENTS_WRITE,
        "statuses": STATUSES_WRITE,
        "id-token": ID_TOKEN_WRITE,
        "pages": PAGES_WRITE,
    }.get(key)
    wanted = "read" if key == "actions" else "write"
    if table is not None and level in {wanted, "write"} and (name, str(job)) not in table:
        return f"{where}: '{key}: {level}' is not on the allow-list for {name}"
    return None


def _permissions(name: str, doc: Doc) -> list[str]:
    out = [] if "permissions" in doc else ["missing top-level permissions: key"]
    for job, perms in _perm_scopes(doc):
        if perms == "write-all":
            out.append(f"{job or 'workflow level'}: permissions write-all is forbidden")
        if isinstance(perms, dict):
            found = [_grant(name, job, str(k), str(v)) for k, v in perms.items()]
            out += [f for f in found if f]
    return out


def _secrets_and_envs(name: str, doc: Doc) -> list[str]:
    out = []
    for ref in sorted(set(SECRET_REF.findall("\n".join(strings(doc))))):
        if "PAT" in ref.upper():
            out.append(f"secrets.{ref}: no PAT secret in a public workflow (security C12)")
        elif ref.upper().startswith("BOT_APP_") and name != GATE_ROUTER:
            out.append(f"secrets.{ref} is usable in {GATE_ROUTER} only (R13 P1.1)")
    for job_id, job in jobs(doc).items():
        if environment(job) == GATE_ROUTER_ENV and name != GATE_ROUTER:
            out.append(
                f"job {job_id}: environment {GATE_ROUTER_ENV} is usable in {GATE_ROUTER} only"
            )
    return out


def _untrusted(code: str) -> bool:
    """True if a ``${{ }}`` expression in ``code`` reads an attacker-controlled context value."""
    for expression in EXPRESSION.findall(code):
        normalised = BRACKET_NAME.sub(r".\1", expression).lower()
        if UNTRUSTED.search(normalised):
            return True
    return False


def _injection(doc: Doc) -> list[str]:
    out = []
    for job_id, job in jobs(doc).items():
        for step in steps(job):
            with_ = step.get("with")
            code = [step.get("run"), with_.get("script") if isinstance(with_, dict) else None]
            if any(isinstance(c, str) and _untrusted(c) for c in code):
                out.append(
                    f"job {job_id}: untrusted PR value interpolated in run/script (injection)"
                )
    return out


def _is_action(step: Doc, prefix: str) -> bool:
    return str(step.get("uses", "")).lower().startswith(prefix)


def _build_images(name: str, doc: Doc) -> list[str]:
    if name != BUILD_IMAGES:
        return []
    out = []
    for job_id, job in jobs(doc).items():
        for step in steps(job):
            if _is_action(step, "actions/checkout"):
                with_ = step.get("with")
                ref = with_.get("ref") if isinstance(with_, dict) else None
                if ref != BUILD_IMAGES_REF:
                    out.append(
                        f"job {job_id}: checkout ref must be {BUILD_IMAGES_REF} (head.sha, X2.4)"
                    )
    return out


def _gate_router_job(job_id: str, job: Doc) -> list[str]:
    out = []
    if job.get("permissions") != {"pull-requests": "read"}:
        out.append(f"job {job_id}: permissions must be exactly {{pull-requests: read}}")
    if environment(job) != GATE_ROUTER_ENV:
        out.append(f"job {job_id}: environment must be {GATE_ROUTER_ENV}")
    if "uses" in job:
        out.append(f"job {job_id}: {GATE_ROUTER} must not call a reusable workflow (uses)")
    for step in steps(job):
        if _is_action(step, "actions/checkout"):
            out.append(f"job {job_id}: {GATE_ROUTER} must not use actions/checkout")
        if _is_action(step, "./"):
            out.append(f"job {job_id}: {GATE_ROUTER} must not use a local action")
        if _is_action(step, "actions/download-artifact") or FETCH_PR_CODE.search(
            str(step.get("run", ""))
        ):
            out.append(f"job {job_id}: {GATE_ROUTER} fetches PR code")
        refs = SECRET_REF.findall("\n".join(strings(step)))
        if any(r.upper().startswith("BOT_APP_") for r in refs) and not _is_action(
            step, APP_TOKEN_ACTION
        ):
            out.append(f"job {job_id}: secrets.BOT_APP_* only in a create-github-app-token step")
    return out


def _gate_router(name: str, doc: Doc) -> list[str]:
    if name != GATE_ROUTER or "pull_request_target" not in triggers(doc):
        return []
    out = [] if doc.get("permissions") == {} else ["top-level permissions must be {}"]
    for ref in sorted(set(SECRET_REF.findall("\n".join(strings(doc))))):
        if ref.upper() not in GATE_ROUTER_SECRETS:
            out.append(f"secrets.{ref}: only BOT_APP_ID and BOT_APP_KEY may be referenced")
    for job_id, job in jobs(doc).items():
        out += _gate_router_job(job_id, job)
    return out


def check_text(name: str, text: str) -> list[str]:
    """Check one workflow.

    Args:
        name: File name (not path), e.g. ``ci.yml``; the allow-lists are keyed by it.
        text: The workflow's YAML source.

    Returns:
        Findings as ``"<name>: <message>"``; empty when the workflow passes every rule.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{name}: invalid YAML: {exc}"]
    if not isinstance(doc, dict):
        return [f"{name}: invalid YAML: top level is not a mapping"]
    rules = [
        _pins(doc, text),
        _triggers_and_runners(name, doc),
        _permissions(name, doc),
        _secrets_and_envs(name, doc),
        _injection(doc),
        _build_images(name, doc),
        _gate_router(name, doc),
    ]
    return [f"{name}: {message}" for found in rules for message in found]


def check_dir(path: Path) -> tuple[int, list[str]]:
    """Check every ``*.yml`` / ``*.yaml`` file in ``path``.

    Args:
        path: The workflows directory.

    Returns:
        ``(number of workflows checked, findings)``.
    """
    files = sorted([*path.glob("*.yml"), *path.glob("*.yaml")])
    findings = [
        f for file in files for f in check_text(file.name, file.read_text(encoding="utf-8"))
    ]
    return len(files), findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the guard.

    Args:
        argv: Arguments; one optional workflows directory (default ``.github/workflows``).

    Returns:
        0 when every workflow passes, 1 on findings, 2 when the directory does not exist.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=".github/workflows", type=Path)
    path = parser.parse_args(argv).directory
    if not path.is_dir():
        sys.stderr.write(f"error: {path} is not a directory\n")
        return 2
    count, findings = check_dir(path)
    if count == 0:
        sys.stderr.write(f"error: no workflows found in {path}\n")
        return 2
    if findings:
        sys.stdout.write("\n".join(findings) + "\n")
        return 1
    sys.stdout.write(f"ok: {count} workflows checked\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
