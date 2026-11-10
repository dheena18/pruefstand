"""The gate step of live-e2e.yml, executed with a stubbed ``uv`` (D1000).

Only the control flow of the shell is under test (which runs happen, what the comment says, which
exit code leaves the step); the stub answers ``pruefstand run | baseline fingerprint-check | gate |
report`` the way the real commands do. No model and no target is replaced.
"""

import os
import subprocess
from pathlib import Path

import pytest
from testsupport.workflow_checks import all_steps, load, read

STUB = """#!/usr/bin/env bash
# args: run pruefstand <command> ...
shift
echo "$*" >> "$STUB_LOG"
case "$2" in
  run)
    n=$(wc -l < "$STUB_LOG"); d="runs/run$n"; mkdir -p "$d"
    echo '{"judge_mode":"skipped","cost":{"llm_calls":0},"counts":{}}' > "$d/run.json"
    echo "$d" ;;
  baseline) echo "$STUB_VERDICT" ;;
  gate) exit "${STUB_GATE_RC:-0}" ;;
  report) printf '<!-- marker -->\\nbody\\n' ;;
esac
"""


def gate_script() -> str:
    doc = load(read("live-e2e.yml"))
    return next(str(s["run"]) for _, s in all_steps(doc) if s.get("id") == "gate")


def run_step(
    tmp_path: Path, *, baseline: str, verdict: str, gate_rc: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(STUB, encoding="utf-8")
    (bin_dir / "uv").chmod(0o755)
    (tmp_path / "step.sh").write_text(gate_script(), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_LOG": str(tmp_path / "log"),
        "STUB_VERDICT": verdict,
        "STUB_GATE_RC": str(gate_rc),
        "BASELINE_DIR": baseline,
        "BASELINE_NOTE": "",
        "CONFIG": "c.yaml",
        "TIER": "pr",
        "IS_FORK": "false",
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    (tmp_path / "log").write_text("", encoding="utf-8")
    done = subprocess.run(
        ["bash", "-e", "step.sh"],  # noqa: S607
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=60,
    )  # fmt: skip
    calls = (tmp_path / "log").read_text(encoding="utf-8").splitlines()
    comment = (tmp_path / "comment.md").read_text(encoding="utf-8") if done.returncode == 0 else ""
    return done, calls, comment


def kinds(calls: list[str]) -> list[str]:
    return [c.split()[1] for c in calls]


def test_a_changed_fingerprint_gates_against_a_second_run_and_says_so(tmp_path: Path) -> None:
    done, calls, comment = run_step(
        tmp_path, baseline="runs/old", verdict="changed aaaaaaaaaaaa bbbbbbbbbbbb"
    )
    assert done.returncode == 0, done.stderr
    assert kinds(calls) == ["run", "baseline", "run", "gate", "report"]
    gate = next(c for c in calls if c.startswith("pruefstand gate"))
    assert "--baseline runs/run3" in gate  # the throw-away run, never runs/old
    assert (
        "Baseline not comparable: eval_fingerprint changed "
        "(baseline aaaaaaaaaaaa, candidate bbbbbbbbbbbb)" in comment
    )
    assert "gated against a second run of this commit" in comment
    assert "self_baseline=true" in (tmp_path / "out").read_text(encoding="utf-8")


def test_a_comparable_baseline_is_used_as_before(tmp_path: Path) -> None:
    done, calls, comment = run_step(tmp_path, baseline="runs/old", verdict="comparable")
    assert done.returncode == 0, done.stderr
    assert kinds(calls) == ["run", "baseline", "gate", "report"]
    assert "--baseline runs/old" in calls[2]
    assert "not comparable" not in comment
    assert "self_baseline=false" in (tmp_path / "out").read_text(encoding="utf-8")


def test_no_baseline_keeps_the_first_run_behaviour(tmp_path: Path) -> None:
    done, calls, comment = run_step(tmp_path, baseline="", verdict="comparable")
    assert done.returncode == 0, done.stderr
    assert kinds(calls) == ["run", "run", "gate", "report"]
    assert "No tier-1 baseline on main yet" in comment


def test_an_unreadable_baseline_is_rebaselined_too(tmp_path: Path) -> None:
    done, calls, comment = run_step(tmp_path, baseline="runs/old", verdict="unreadable")
    assert done.returncode == 0, done.stderr
    assert kinds(calls) == ["run", "baseline", "run", "gate", "report"]
    assert "Baseline not comparable: the loaded baseline could not be read" in comment


@pytest.mark.parametrize("verdict", ["comparable", "changed aaaaaaaaaaaa bbbbbbbbbbbb"])
@pytest.mark.parametrize("gate_rc", [1, 3])
def test_a_gate_failure_or_error_still_fails_the_step(
    tmp_path: Path, verdict: str, gate_rc: int
) -> None:
    done, calls, _ = run_step(tmp_path, baseline="runs/old", verdict=verdict, gate_rc=gate_rc)
    if gate_rc > 1:
        assert done.returncode == gate_rc
        assert "report" not in kinds(calls)
    else:
        assert (
            done.returncode == 0
        )  # exit 1 is the gate FAIL: the later step "Gate result" fails the job
        assert "gate_rc=1" in (tmp_path / "out").read_text(encoding="utf-8")


def test_an_unexpected_verdict_fails_the_step(tmp_path: Path) -> None:
    done, _, _ = run_step(tmp_path, baseline="runs/old", verdict="???")
    assert done.returncode != 0
