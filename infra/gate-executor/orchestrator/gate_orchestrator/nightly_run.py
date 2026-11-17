"""The nightly phases on the A40 runner (N4.3, P2.1, P4.4, AI13-08, D298, D299, D305, D1095, D1099).

Order (each phase deadline-checked with :func:`phase_check`): ``switch-mode.sh night`` →
``judge-drift`` of the one judge → the gate phase (main's image as candidate, ``pruefstand run
--tier nightly --split full --stratum all --block auto`` with ``PRUEFSTAND_NIGHTLY_COUNTER``, gate
against ``nightly-b<k>``, drift against ``release-b<k>``) → ``switch-mode.sh day`` (also in
``finally``). A start at or after the deadline is ``aborted: window_exceeded`` (no phase runs); a
phase that does not fit stops the night the same way. The weekly cause-switches, the contamination
probe and the prune phases come in a later slice (D1099).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from gate_orchestrator.gate_job import Attempt
from gate_orchestrator.gate_run import run_config
from gate_orchestrator.infra import InfraError
from gate_orchestrator.window import baseline_refs

PLANNED_MINUTES = {"switch-mode": 5.0, "judge-drift": 5.0, "nightly-gate": 360.0, "drift": 15.0}
JUDGE = "ollama/gemma3:12b"  # the one judge for PR and nightly (ADR-0019)


def nightly_run_argv(config: Path, runs: Path) -> list[str]:
    """``pruefstand run`` of one night: refusal stratum + block ``auto`` of ``full`` (D298)."""
    return [
        "pruefstand", "run", "--config", str(config), "--tier", "nightly", "--out", str(runs),
        "--split", "full", "--stratum", "all", "--block", "auto",
    ]  # fmt: skip


def nightly_gate_argvs(run_dir: Path, config: Path, block: int) -> list[list[str]]:
    """Gate against ``nightly-b<k>``, then drift against ``release-b<k>`` (N1.4, D305)."""
    gate_ref, drift_ref = baseline_refs(block)
    base = [
        "pruefstand",
        "gate",
        "--candidate",
        str(run_dir),
        "--from-store",
        "--config",
        str(config),
    ]
    return [[*base, "--ref", gate_ref], [*base, "--ref", drift_ref]]


def read_manifest(run_dir: Path) -> dict[str, object]:
    """``run.json`` of a run; a missing or corrupt file is the infra error ``run_failed``.

    Raises:
        InfraError: ``run.json`` is missing, unreadable or not a JSON object.
    """
    try:
        data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"run_failed: no readable run.json in {run_dir.name}"
        raise InfraError(msg) from exc
    if not isinstance(data, dict):
        msg = f"run_failed: {run_dir.name}/run.json is not an object"
        raise InfraError(msg)
    return data


def gate_failed(code: int) -> bool:
    """``pruefstand gate`` exit: 0 → passed (incl. INSUFFICIENT_DATA), 1 → FAIL (review #236).

    Raises:
        InfraError: any other exit (2 config/usage, 3 runtime error): no gate decision was made.
    """
    if code in (0, 1):
        return code == 1
    msg = f"gate_failed: pruefstand gate exit {code}"
    raise InfraError(msg)


@dataclass
class NightlyRun(Attempt):
    """A gate attempt that runs the nightly split against main's image; result = run status."""

    counter: int = 0
    run_dir: Path | None = None
    runs_dir: Path | None = None  # $PRUEFSTAND_HOME/runs: promote-poll finds the night there

    def _run_and_gate(self, url: str) -> str | None:
        config = run_config(self.main_config, self.work / "pruefstand.yaml", url)
        env = {**self.env, "PRUEFSTAND_NIGHTLY_COUNTER": str(self.counter)}
        code, out = self.run(nightly_run_argv(config, self.runs_dir or self.work / "runs"), env)
        lines = out.strip().splitlines()
        if code != 0 or not lines:
            msg = f"run_failed: pruefstand run exit {code}"
            raise InfraError(msg)
        self.run_dir = Path(lines[-1])
        manifest = read_manifest(self.run_dir)
        if manifest.get("infra_error"):
            return str(manifest["infra_error"])
        block = manifest.get("block")
        failed = False
        if isinstance(block, int):
            gate, drift = nightly_gate_argvs(self.run_dir, config, block)
            failed = gate_failed(self.run(gate, env)[0])
            self.run(drift, env)  # drift is reported in gate.json of the drift run, never gating
        self.result = "failed" if failed else "ok"
        return None
