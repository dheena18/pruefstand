"""Rules over the parsed tier-1 workflows (T1.12 S6): each returns its findings, none is a pass.

Shared by the tests of the real files and by those of mutated copies."""

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"
SAME_REPO = (
    "github.event_name == 'pull_request' && "
    "github.event.pull_request.head.repo.full_name == github.repository"
)
MARKER_EXPRESSION = '"live and not e2e and not gpu and not network"'
SCENARIOS = [
    "good",
    "tenant_filter_post_topk",
    "shared_public_unfiltered",
    "system_prompt_guard_off",
    "injection_guard_off",
]
Doc = dict[str, Any]
Check = Callable[[Doc, str], list[str]]


def read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def load(text: str) -> Doc:
    doc: Doc = yaml.safe_load(text)
    return doc


def steps(job: Doc) -> list[Doc]:
    found: list[Doc] = job.get("steps", [])
    return found


def all_steps(doc: Doc) -> Iterator[tuple[str, Doc]]:
    for job_id, job in doc["jobs"].items():
        for step in steps(job):
            yield job_id, step


def triggers(doc: Doc) -> dict[str, Any]:
    keys = {str(key): value for key, value in doc.items()}  # PyYAML reads the key `on` as True
    found: dict[str, Any] = keys.get("on") or keys["True"]
    return found


# --- the checks -------------------------------------------------------------------------------


def check_comment_jobs(doc: Doc, _text: str) -> list[str]:
    out = []
    for job_id, job in doc["jobs"].items():
        permissions = job.get("permissions") or {}
        if permissions.get("pull-requests") != "write":
            continue
        if SAME_REPO not in str(job.get("if", "")):
            out.append(f"{job_id}: no same-repo condition")
        if permissions != {"contents": "read", "pull-requests": "write"}:
            out.append(f"{job_id}: permissions are {permissions}")
    return out


def check_baseline_lookup(doc: Doc, _text: str) -> list[str]:
    """PR runs look up `live-baseline` by branch, status and event=push; nothing else."""
    out = []
    for job_id, step in all_steps(doc):
        run = str(step.get("run", ""))
        if "actions/workflows/live-e2e.yml/runs" not in run or "event=schedule" in run:
            continue
        for part in ("branch=main", "status=success", "event=push"):
            if part not in run:
                out.append(f"{job_id}: lookup lacks {part}")
        if "--name live-baseline " not in run:
            out.append(f"{job_id}: lookup does not download live-baseline")
    if not any("event=push" in str(s.get("run", "")) for _, s in all_steps(doc)):
        out.append("no PR baseline lookup")
    return out


def check_fingerprint_rebaseline(doc: Doc, _text: str) -> list[str]:
    """A baseline of another eval_fingerprint is treated as no baseline, not as an error (D1000)."""
    gate = next((s for _, s in all_steps(doc) if s.get("id") == "gate"), None)
    if gate is None:
        return ["no gate step"]
    run = str(gate.get("run", ""))
    out = []
    for part in (
        "pruefstand baseline fingerprint-check",
        'case "$verdict" in',
        'base=""',
        "self=true",
        "Baseline not comparable:",
    ):
        if part not in run:
            out.append(f"the gate step lacks {part}")
    if run.count("pruefstand gate ") != 1 or "|| gate_rc=$?" not in run:
        out.append("the gate command must run once and keep its exit code")
    if 'if [ "$gate_rc" -gt 1 ]; then exit "$gate_rc"; fi' not in run:
        out.append("the gate step no longer fails on a gate error")
    return out


def check_uploads(doc: Doc, _text: str) -> list[str]:
    out = []
    for job_id, step in all_steps(doc):
        name = (step.get("with") or {}).get("name")
        condition = str(step.get("if", ""))
        if name == "live-baseline" and "github.event_name == 'push'" not in condition:
            out.append(f"{job_id}: live-baseline is uploaded outside push")
        if name == "live-baseline-nightly" and "github.event_name == 'schedule'" not in condition:
            out.append(f"{job_id}: live-baseline-nightly is uploaded outside schedule")
    run_step = next(s for _, s in all_steps(doc) if s.get("id") == "gate")
    expression = run_step["env"]["CONFIG"]
    if not expression.endswith("|| 'examples/live/pruefstand.yaml' }}"):
        out.append("push runs do not use examples/live/pruefstand.yaml")
    if "'examples/live/pruefstand.nightly.yaml'" not in expression:
        out.append("the nightly does not use the nightly config")
    return out


def check_marker(doc: Doc, _text: str) -> list[str]:
    runs = [str(s.get("run", "")) for _, s in all_steps(doc)]
    pytest_runs = [r for r in runs if "pytest -m" in r and "e2e and live" not in r]
    ok = [f"pytest -m {MARKER_EXPRESSION} " in r for r in pytest_runs]
    return [] if ok and all(ok) else ["the live job's marker expression is not the D9-16 one"]


def check_cache_saves(doc: Doc, _text: str) -> list[str]:
    return [
        f"{job_id}: cache/save without a refs/heads/main condition"
        for job_id, step in all_steps(doc)
        if str(step.get("uses", "")).startswith("actions/cache/save@")
        and "github.ref == 'refs/heads/main'" not in str(step.get("if", ""))
    ]


def check_no_judge_mode(_doc: Doc, text: str) -> list[str]:
    bad = re.findall(r"PRUEFSTAND_JUDGE_MODE[=:]\s*\"?(cpu|github)\b", text)
    return [f"PRUEFSTAND_JUDGE_MODE set to {m}" for m in bad]


def check_no_gate_status(_doc: Doc, text: str) -> list[str]:
    return ["mentions pruefstand/gate"] if "pruefstand/gate" in text else []


def check_secrets(_doc: Doc, text: str) -> list[str]:
    refs = re.findall(r"secrets\.([A-Za-z0-9_]+)", text)
    return [f"secrets.{r}" for r in refs if r != "GITHUB_TOKEN"]


def check_comment_checkout(doc: Doc, _text: str) -> list[str]:
    job = doc["jobs"]["comment"]
    checkout = next(s for s in steps(job) if str(s.get("uses", "")).startswith("actions/checkout@"))
    if (checkout.get("with") or {}).get("ref") != "${{ github.event.pull_request.base.sha }}":
        return ["the comment job does not check out the base SHA"]
    if "action/check_comment.py" not in "".join(str(s.get("run", "")) for s in steps(job)):
        return ["the comment job does not run check_comment.py"]
    return []


def mutated(check: Check, old: str, new: str, name: str = "live-e2e.yml") -> list[str]:
    """Findings of ``check`` on workflow ``name`` after replacing ``old`` by ``new``."""
    text = read(name)
    assert old in text, old
    changed = text.replace(old, new)
    assert changed != text
    return check(load(changed), changed)
