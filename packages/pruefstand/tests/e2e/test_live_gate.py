"""The real CLI against the real rag-demo: the gate passes `good` and catches each bug switch.

Needs the `live` stack with the indexed slice (`make e2e-live` starts it under stack.lock).
Assertions are on gate outcomes and directions, never on answer text (real models are not
byte-deterministic).
`PRUEFSTAND_E2E_SCENARIO=<name>` runs one scenario (CI: one matrix job per scenario, T1.12).
"""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from testsupport.e2e_support import DATASET, call, run_dir, start_bug, stop_bug, write_config

pytestmark = [pytest.mark.e2e, pytest.mark.live]

MARKER = "<!-- pruefstand:pr-comment -->"
LIMIT_S = 20 * 60
REASON_PAIRED = "tier1_deterministic_only"
REASON_INJECTION = "tier1_injection_reported"
Baseline = tuple[Path, float]


@dataclass(frozen=True)
class Played:
    """One scenario: the gate's exit code, ``gate.json``, the Markdown report and the wall time."""

    exit_code: int
    gate: dict[str, Any]
    markdown: str
    seconds: float

    def hard_fail_cases(self, metric: str) -> set[str]:
        """Case ids with a hard fail on ``metric``."""
        return {h["case_id"] for h in self.gate["hard_fails"] if h["metric"] == metric}

    def absolute(self, metric: str) -> dict[str, Any]:
        """The overall absolute-check row of ``metric``."""
        (row,) = [
            r
            for r in self.gate["absolute_checks"]
            if r["metric"] == metric and r["dimension"] == "overall"
        ]
        found: dict[str, Any] = row
        return found


def _case_ids(category: str) -> set[str]:
    ids: set[str] = set()
    for name in ("smoke_live", "smoke"):
        for line in (DATASET / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["category"] == category:
                ids.add(row["id"])
    return ids


def _play(
    scenario: str, bug: str | None, *, target_url: str, baseline: Path, tmp_path: Path
) -> Played:
    """Run, gate and report the scenario's target against ``baseline``."""
    url = start_bug(bug) if bug else target_url
    try:
        config = write_config(scenario, url, tmp_path)
        # same --out as the baseline: `report` looks the baseline run up next to the candidate
        done = call("run", "--config", str(config), "--tier", "pr", "--out", str(baseline.parent))
        candidate = run_dir(done)
        args = ["--config", str(config), "--candidate", str(candidate), "--baseline", str(baseline)]
        gated = call("gate", *args)
        rendered = call("report", "--run", str(candidate), "--format", "md")
    finally:
        if bug:
            stop_bug(bug)
    assert rendered.exit_code == 0, rendered.output
    gate = json.loads((candidate / "gate.json").read_text(encoding="utf-8"))
    keep = os.environ.get("PRUEFSTAND_E2E_KEEP")
    if keep:  # CI uploads this run directory; the dashboard fixtures are made from it (T8.1)
        shutil.copytree(candidate, Path(keep) / candidate.name, dirs_exist_ok=True)
    seconds = done.seconds + gated.seconds + rendered.seconds
    return Played(gated.exit_code, gate, rendered.stdout, seconds)


def _common(request: pytest.FixtureRequest, name: str, played: Played, base: Baseline) -> None:
    """Checks every scenario shares: the PR-comment marker, the 20 minute limit, the timing line."""
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            f"[e2e] {name}: gate exit {played.exit_code}, status {played.gate['status']}, "
            f"wall {played.seconds:.0f} s (baseline run {base[1]:.0f} s)"
        )
    assert played.markdown.splitlines()[0] == MARKER
    assert played.seconds <= LIMIT_S, f"{name} took {played.seconds:.0f} s"
    assert base[1] <= LIMIT_S, f"the baseline run took {base[1]:.0f} s"


def test_good(
    request: pytest.FixtureRequest, target_url: str, baseline: Baseline, tmp_path: Path
) -> None:
    played = _play("good", None, target_url=target_url, baseline=baseline[0], tmp_path=tmp_path)
    _common(request, "good", played, baseline)
    assert played.exit_code == 0
    assert played.gate["status"] == "pass"
    assert played.gate["hard_fails"] == []
    assert played.gate["decisions"] == [], "tier 1 gates no paired row"
    paired = played.gate["notable_slices"]  # every paired row that does not gate
    assert paired, "no paired rows: the gate compared nothing"
    for row in paired:
        assert row["gated"] is False, row["metric"]
        assert row["informational_reason"] == REASON_PAIRED, (row["metric"], row["dimension"])
    injection = played.absolute("injection_success")
    assert injection["gated"] is False
    assert injection["informational_reason"] == REASON_INJECTION
    assert injection["candidate_mean"] == 0, "guard on: no planted injection may succeed (T1.13 S7)"
    assert played.absolute("error_rate")["status"] == "pass"
    assert "Tier 1 decides on hard fails and the error rate only" in played.markdown
    assert "does not decide at n = 40" in played.markdown


def test_tenant_filter_post_topk(
    request: pytest.FixtureRequest, target_url: str, baseline: Baseline, tmp_path: Path
) -> None:
    bug = "tenant_filter_post_topk"
    played = _play(bug, bug, target_url=target_url, baseline=baseline[0], tmp_path=tmp_path)
    _common(request, bug, played, baseline)
    assert played.exit_code == 1
    assert played.gate["status"] == "fail"
    assert _case_ids("leak_probe") <= played.hard_fail_cases("tenant_leak")


def test_shared_public_unfiltered(
    request: pytest.FixtureRequest, target_url: str, baseline: Baseline, tmp_path: Path
) -> None:
    bug = "shared_public_unfiltered"
    played = _play(bug, bug, target_url=target_url, baseline=baseline[0], tmp_path=tmp_path)
    _common(request, bug, played, baseline)
    assert played.exit_code == 1
    assert played.hard_fail_cases("tenant_leak"), "no tenant_leak hard fail"


def test_system_prompt_guard_off(
    request: pytest.FixtureRequest, target_url: str, baseline: Baseline, tmp_path: Path
) -> None:
    bug = "system_prompt_guard_off"
    played = _play(bug, bug, target_url=target_url, baseline=baseline[0], tmp_path=tmp_path)
    _common(request, bug, played, baseline)
    assert played.exit_code == 1
    assert played.hard_fail_cases("system_prompt_leak") <= _case_ids("system_prompt_extraction")
    assert played.hard_fail_cases("system_prompt_leak"), "no system_prompt_leak hard fail"


def test_injection_guard_off(
    request: pytest.FixtureRequest, target_url: str, baseline: Baseline, tmp_path: Path
) -> None:
    bug = "injection_guard_off"
    played = _play(bug, bug, target_url=target_url, baseline=baseline[0], tmp_path=tmp_path)
    _common(request, bug, played, baseline)
    assert played.exit_code == 0, "injection is reported, not gating, in tier 1 (X3.11)"
    injection = played.absolute("injection_success")
    assert injection["gated"] is False
    assert injection["informational_reason"] == REASON_INJECTION
    assert injection["candidate_mean"] > 0, "re-pin generator or injection docs (T1.13 S7)"
    assert injection["notable"] is True
