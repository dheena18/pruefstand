"""Guard for the PRIVATE executor workflows (T6.2b; prompt test table, ci-cd.md section 1.2; D1093).

The files live in ``infra/gate-executor/workflows/`` of this repo and run in the private repo
``dheena18/pruefstand-gate`` after ``scripts/sync_executor.sh``. Usage:
``python scripts/workflow_private.py [infra/gate-executor/workflows]``: prints ``ok: N private
workflows checked`` and exits 0, or one finding per line and exits 1.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml
from workflow_hardening import pins
from workflow_model import Doc, jobs, steps, strings, triggers
from workflow_schedule import crons

FILES = frozenset({"gate-executor.yml", "baseline-promote.yml", "nightly.yml", "backup.yml"})
A40 = "a40"
DISPATCH_GROUP = "${{ github.workflow }}-${{ inputs.pr || inputs.sha }}"
WORKFLOW_GROUP = "${{ github.workflow }}"
NIGHTLY_CRONS = frozenset({"7 20 * * *", "7 21 * * *"})
NIGHTLY_IF = "needs.guard.outputs.run == 'true'"
NIGHTLY_FORBIDDEN_JOBS = frozenset(
    {"simulation-full", "hypothesis-full", "mutmut", "baseline-prune"}
)
QUARTER_MINUTES = frozenset({0, 15, 30, 45})
# X2.1: GPU lock and infra/gpu scripts belong to the orchestrator, never to a workflow step.
HOST_TOOLS = re.compile(r"(?<![\w.-])(flock|switch-mode\.sh|health\.sh|fetch-model\.sh)(?![\w.-])")
SECRET_REF = re.compile(r"secrets\s*[.\[]", re.IGNORECASE)


def _map(value: object) -> Doc:
    return value if isinstance(value, dict) else {}


def _schedule(doc: Doc) -> list[Doc]:
    raw = triggers(doc).get("schedule")
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _runs_on(job: Doc) -> list[str]:
    raw = job.get("runs-on")
    return [str(v) for v in raw] if isinstance(raw, list) else [str(raw)]


def _common(name: str, doc: Doc) -> list[str]:
    out = [] if doc.get("permissions") == {} else ["top-level permissions must be {}"]
    extra = sorted(str(t) for t in triggers(doc) if t not in {"schedule", "workflow_dispatch"})
    if extra:
        out.append(f"triggers must be schedule/workflow_dispatch only, found {extra}")
    out += crons(doc)
    for entry in _schedule(doc):
        minute = str(entry.get("cron", "")).split(" ", 1)[0]
        if any(p.isdigit() and int(p) in QUARTER_MINUTES for p in minute.split(",")):
            out.append(f"schedule '{entry.get('cron')}': minute on 0/15/30/45 (R9-22)")
    group = DISPATCH_GROUP if name == "gate-executor.yml" else WORKFLOW_GROUP
    conc = doc.get("concurrency")
    if not isinstance(conc, dict) or conc.get("group") != group:
        out.append(f"concurrency.group must be exactly {group}")
    elif conc.get("cancel-in-progress") is not False:
        out.append("concurrency.cancel-in-progress must be false")
    if "run-gate" in "\n".join(strings(doc)):
        out.append("mentions run-gate (P1.2: there is no run-gate label)")
    return out


def _job(name: str, job_id: str, job: Doc) -> list[str]:
    out = []
    hosted_guard = name == "nightly.yml" and job_id == "guard"
    if hosted_guard:
        if _runs_on(job) != ["ubuntu-24.04"]:
            out.append("job guard: must run on hosted ubuntu-24.04 (A12-03)")
        if any(SECRET_REF.search(s) for s in strings(job)):
            out.append("job guard: uses a secret")
    elif A40 not in _runs_on(job):
        out.append(f"job {job_id}: runs-on must include {A40}")
    if not isinstance(job.get("timeout-minutes"), int):
        out.append(f"job {job_id}: missing timeout-minutes")
    out += [f"job {job_id}: {m}" for step in steps(job) for m in _step(step)]
    return out


def _step(step: Doc) -> list[str]:
    run = str(step.get("run", ""))
    out = []
    if HOST_TOOLS.search(run):
        out.append("a step calls flock or an infra/gpu script (X2.1)")
    if "gh workflow run baseline-promote" in run:
        out.append("dispatches baseline-promote")
    uploads = str(step.get("uses", "")).startswith("actions/upload-artifact@")
    if uploads and _map(step.get("with")).get("retention-days") != 14:
        out.append("upload-artifact needs retention-days: 14")
    return out


def _gate_executor(doc: Doc) -> list[str]:
    on = triggers(doc)
    pr = _map(_map(on.get("workflow_dispatch")).get("inputs")).get("pr")
    if (
        set(on) != {"workflow_dispatch"}
        or not isinstance(pr, dict)
        or pr.get("required") is not True
    ):
        return ["gate-executor.yml: only trigger workflow_dispatch with required input pr (P1.2)"]
    return []


def _nightly(doc: Doc) -> list[str]:
    out = []
    found = {str(e.get("cron")) for e in _schedule(doc)}
    if found != NIGHTLY_CRONS:
        out.append(f"nightly crons must be exactly {sorted(NIGHTLY_CRONS)}")
    all_jobs = jobs(doc)
    if set(all_jobs) != {"guard", "nightly"}:
        out.append("nightly.yml must have exactly the jobs guard and nightly (N4.3)")
    if NIGHTLY_FORBIDDEN_JOBS & set(all_jobs):
        out.append("nightly.yml runs a CPU-only or prune job (R9-13, R9-14)")
    guard, nightly = all_jobs.get("guard", {}), all_jobs.get("nightly", {})
    guard_text = "\n".join(strings(guard))
    outputs = guard.get("outputs") or {}
    if "night-guard --schedule" not in guard_text or "github.event.schedule" not in guard_text:
        out.append("job guard: must pass github.event.schedule to night-guard --schedule")
    if not isinstance(outputs, dict) or not {"run", "deadline"} <= set(outputs):
        out.append("job guard: must declare outputs run and deadline")
    if nightly.get("needs") not in ("guard", ["guard"]) or nightly.get("if") != NIGHTLY_IF:
        out.append(f"job nightly: needs guard and if: {NIGHTLY_IF} (P2.1)")
    nightly_text = "\n".join(strings(nightly))
    if "gate-orchestrator nightly --deadline" not in nightly_text or (
        "needs.guard.outputs.deadline" not in nightly_text
    ):
        out.append("job nightly: must run gate-orchestrator nightly --deadline <guard deadline>")
    return out


def check_private_text(name: str, text: str) -> list[str]:
    """Check one private workflow; findings as ``"<name>: <message>"``."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{name}: invalid YAML: {exc}"]
    if not isinstance(doc, dict):
        return [f"{name}: invalid YAML: top level is not a mapping"]
    found = pins(doc, text) + _common(name, doc)
    for job_id, job in jobs(doc).items():
        found += _job(name, job_id, job)
    if name == "gate-executor.yml":
        found += _gate_executor(doc)
    if name == "nightly.yml":
        found += _nightly(doc)
    return [f"{name}: {message}" for message in found]


def check_private_dir(path: Path) -> tuple[int, list[str]]:
    """Check the private workflow directory: exactly the four files, each passing every rule."""
    files = sorted([*path.glob("*.yml"), *path.glob("*.yaml")])
    names = {f.name for f in files}
    findings = [f"{path}: missing {n}" for n in sorted(FILES - names)]
    findings += [f"{path}: unexpected private workflow {n}" for n in sorted(names - FILES)]
    for file in files:
        findings += check_private_text(file.name, file.read_text(encoding="utf-8"))
    return len(files), findings


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: 0 ok, 1 findings, 2 no such directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="infra/gate-executor/workflows", type=Path)
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        sys.stderr.write(f"error: {args.directory} is not a directory\n")
        return 2
    count, findings = check_private_dir(args.directory)
    if findings:
        sys.stdout.write("\n".join(findings) + "\n")
        return 1
    sys.stdout.write(f"ok: {count} private workflows checked\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
