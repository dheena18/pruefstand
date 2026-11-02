r"""Turn probe.sh / tunnel_check.sh output into a Markdown table and a go / no-go verdict (T0.6 S3).

Input (stdin): lines ``CHECK <id> <PASS|FAIL|WARN> <detail>``; blank lines and ``#`` comments are
skipped, anything else is reported as an ignored line. Output: a Markdown table, the conditions and
a last line ``VERDICT: go|go-with-conditions|no-go``. The exit code is always 0 (the verdict is
data).

An id may appear several times (a normal run, a ``MEASURE_LOAD`` run and the tunnel check are
concatenated): the last line wins, except that a ``SKIP`` line never overrides a measured one. The
table, the conditions and the verdict use the winning lines only.

Example:
    >>> text = "CHECK gpu PASS 2 x A40\\nCHECK net WARN huggingface unreachable\\n"
    >>> out = summarise(text)
    >>> out.splitlines()[-1]
    'VERDICT: no-go'
"""

import re
import sys
from dataclasses import dataclass

GO_CHECKS = (
    "gpu",
    "ollama",
    "detached-survives-logout",
    "models-space",
    "net",
    "fwd",
    "api-tags",
    "api-chat-nothink",
    "api-ctx",
)
INFORMATIONAL = frozenset({"docker", "vllm", "tmux", "logind", "local-disk", "api-openai"})
STATUSES = ("PASS", "WARN", "FAIL")
_LINE = re.compile(r"^CHECK\s+(\S+)\s+(PASS|FAIL|WARN)(?:\s+(.*))?$")
_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}

_WARN_CONDITIONS = {
    "models-space": "free space on /data first (swap rule, ADR-0019)",
    "ollama-list": "generator tag missing: pull it (T3.1a S2b)",
    "ollama-store": (
        "server env differs from setup log §7: fix ~/start-ollama.sh (owner step, runbook §2a)"
    ),
    "gpu-procs": "VRAM held by another process",
    "port-11434": "port held by another owner or unit: stop it or use free ports",
    "ollama-provenance": "local-only tag: back up blobs + manifest (T3.1a S2b)",
}


@dataclass(frozen=True)
class Check:
    """One parsed probe line."""

    id: str
    status: str
    detail: str


def parse_checks(text: str) -> tuple[list[Check], list[str]]:
    """Split probe output into checks and ignored (malformed) lines.

    Args:
        text: Raw probe and tunnel output.

    Returns:
        The parsed checks in input order and the non-blank, non-comment lines that did not parse.
    """
    checks: list[Check] = []
    bad: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            bad.append(line)
            continue
        checks.append(Check(match.group(1), match.group(2), (match.group(3) or "").strip()))
    return checks, bad


def _is_skip(check: Check) -> bool:
    return check.status == "PASS" and check.detail.startswith("SKIP")


def _winning(checks: list[Check]) -> dict[str, Check]:
    """One line per id in first-seen order: the last real result; SKIP never beats a real one."""
    won: dict[str, Check] = {}
    for check in checks:
        current = won.get(check.id)
        if current is not None and _is_skip(check) and not _is_skip(current):
            continue
        won[check.id] = check
    return won


def _minutes(detail: str) -> str:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*min", detail)
    if match:
        return f"{match.group(1)} min"
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*s\b", detail)
    if match:
        return f"{float(match.group(1).replace(',', '.')) / 60:.1f} min"
    return f"unknown ({detail})"


def _kill_user_processes(by_id: dict[str, Check]) -> str:
    logind = by_id.get("logind")
    match = re.search(r"KillUserProcesses=(\S+)", logind.detail) if logind else None
    return match.group(1) if match else "unknown"


def _condition(check: Check, by_id: dict[str, Check]) -> str:
    """One condition line for a WARN, or for a FAIL / missing go check."""
    cid, detail = check.id, check.detail
    if cid == "detached-survives-logout" and check.status == "FAIL":
        value = _kill_user_processes(by_id)
        return (
            f"servers die at SSH logout (KillUserProcesses={value}): "
            "the admin must allow detached processes or enable linger"
        )
    if cid == "fwd" and "in use" in detail:
        return f"fwd FAIL: {detail}; set PROBE_PORT0 to a free local port"
    if check.status == "FAIL":
        return f"{cid} FAIL: {detail}"
    if cid == "model-load":
        return f"first model load ≈ {_minutes(detail)}; excluded from budgets"
    return f"{cid} WARN: {_WARN_CONDITIONS.get(cid, detail)}" + (f" ({detail})" if detail else "")


def _verdict(checks: list[Check]) -> tuple[str, list[str]]:
    if not checks:
        return "no-go", ["no checks: the probe produced no CHECK lines"]
    by_id = _winning(checks)
    conditions: list[str] = []
    no_go = False
    for cid in GO_CHECKS:
        check = by_id.get(cid)
        if check is None:
            no_go = True
            conditions.append(f"{cid}: check missing (run probe.sh and tunnel_check.sh)")
        elif check.status == "FAIL":
            no_go = True
            conditions.append(_condition(check, by_id))
    for cid, check in by_id.items():
        if cid == "model-load" and _is_skip(check):
            conditions.append(
                "model-load: cold load not measured (opt-in MEASURE_LOAD=1, owner step)"
            )
            continue
        if cid in INFORMATIONAL or check.status == "PASS":
            continue
        if cid in GO_CHECKS and check.status == "FAIL":
            continue
        conditions.append(_condition(check, by_id))
    if no_go:
        return "no-go", conditions
    return ("go-with-conditions" if conditions else "go"), conditions


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def summarise(text: str) -> str:
    """Render the Markdown report for probe output.

    Args:
        text: Raw probe and tunnel output.

    Returns:
        A table (one row per id, winning line), the conditions and the final VERDICT line.
    """
    checks, bad = parse_checks(text)
    rows = ["| id | status | detail |", "| --- | --- | --- |"]
    rows += [f"| {c.id} | {c.status} | {_cell(c.detail)} |" for c in _winning(checks).values()]
    rows += [f"| ? | WARN | ignored line: {_cell(line)} |" for line in bad]
    verdict, conditions = _verdict(checks)
    out = [*rows, "", "Conditions:", ""]
    out += [f"- {line}" for line in conditions] or ["- none"]
    out += ["", f"VERDICT: {verdict}"]
    return "\n".join(out) + "\n"


def main() -> int:
    """Read stdin, print the report, return 0 (the verdict is data, not an exit code)."""
    sys.stdout.write(summarise(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
