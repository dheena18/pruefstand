"""State and selection of one ``baseline-promote.yml`` poll (R9-14, N1.4, D321, D1095).

A poll does, in order: (1) a new public ``main`` head with a signed image → a PR-tier run of main's
image, then ``gate`` + ``baseline promote --ref main`` (:class:`MainPromotion`, under the GPU
lock); (2) the newest promotable nightly or release run in ``$PRUEFSTAND_HOME/runs/`` → its refs
(``nightly-b<k>`` or ``release-b0..b2``) through #221's ``promotion_commands``; (3) the monthly
``baseline prune --keep 20``. State files under ``$PRUEFSTAND_HOME/state/``: ``promote_main_sha``
(last main head handled), ``promoted_runs.txt`` (``<run_id> <ref> <status>`` lines, so a refused
run is never retried on every poll) and ``last_prune`` (``YYYY-MM``).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gate_orchestrator.gate_job import Attempt
from gate_orchestrator.gate_run import pruefstand_run_argv, run_config
from gate_orchestrator.infra import InfraError
from gate_orchestrator.nightly import RunInfo
from gate_orchestrator.promote import interpret_promote_exit, promotion_commands

PRUNE_ARGV = ["pruefstand", "baseline", "prune", "--keep", "20"]


def read_text(path: Path) -> str:
    """Stripped content, or ``""`` when the file is missing."""
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def promoted_run_ids(path: Path) -> set[str]:
    """Run ids already handled (promoted or refused) in ``promoted_runs.txt``."""
    return {line.split()[0] for line in read_text(path).splitlines() if line.split()}


def last_prune(path: Path) -> tuple[int, int] | None:
    """``(year, month)`` of the last prune, or ``None``."""
    text = read_text(path)
    try:
        year, month = (int(p) for p in text.split("-"))
    except ValueError:
        return None
    return year, month


def run_info(run_json: Mapping[str, object], promoted: set[str]) -> RunInfo | None:
    """A :class:`RunInfo` for a nightly or release run's ``run.json``; ``None`` for other runs."""
    if run_json.get("workload") != "nightly":
        return None
    block = run_json.get("block")
    run_id = str(run_json.get("run_id", ""))
    return RunInfo(
        run_id=run_id,
        kind="nightly" if isinstance(block, int) else "release",
        block=block if isinstance(block, int) else None,
        complete=run_json.get("complete") is True,
        promoted=run_id in promoted,
        judge_fallback=run_json.get("judge_fallback") is True,
        judge_drift=run_json.get("judge_drift") is True,
        judge_degraded=run_json.get("judge_degraded") is True,
        infra_error=str(run_json["infra_error"]) if run_json.get("infra_error") else None,
    )


def scan_runs(runs: Path, promoted: set[str]) -> dict[str, tuple[RunInfo, Path]]:
    """Nightly and release runs below ``runs/`` (one ``run.json`` per run directory)."""
    found: dict[str, tuple[RunInfo, Path]] = {}
    for run_json in sorted(runs.glob("*/run.json")) if runs.is_dir() else []:
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        info = run_info(data, promoted) if isinstance(data, dict) else None
        if info is not None and info.run_id:
            found[info.run_id] = (info, run_json.parent)
    return found


@dataclass
class MainPromotion(Attempt):
    """A gate attempt that runs main's image and promotes the run to ``main`` (no PR status)."""

    def _run_and_gate(self, url: str) -> str | None:
        config = run_config(self.main_config, self.work / "pruefstand.yaml", url)
        code, out = self.run(
            pruefstand_run_argv(config, self.work / "runs", judged_subset=False), self.env
        )
        lines = out.strip().splitlines()
        if code != 0 or not lines:
            msg = f"run_failed: pruefstand run exit {code}"
            raise InfraError(msg)
        run_dir = Path(lines[-1])
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if manifest.get("infra_error"):
            return str(manifest["infra_error"])
        env = {**self.env, "PRUEFSTAND_CONFIG": str(config)}
        code = 0
        for argv in promotion_commands(str(run_dir), "main"):
            code, _ = self.run(argv, env)
        self.result = interpret_promote_exit(code, run_dir.name, "main").summary
        return None
