"""The weekly cause-switches phase of the nightly (T6.3 S4, T6.2b S4; Y4.3, AI12-10, P4.3, D1027).

Sunday nights only (``cause_switches_due``; ``--cause-switches force|skip`` overrides). For each
scenario of ``experiments/noise/cause_switches.py --plan`` (in the pinned main worktree) the
orchestrator serves main's verified image twice in the sandbox, once with ``rag.gpu.yaml`` and once
with the scenario's ``configs/cause/*.yaml``, runs each planned ``pruefstand run`` against it (the
plan's config with ``target.url`` set to the candidate, the plan's env such as
``PRUEFSTAND_JUDGE_MODE=skipped``) and then ``cause_switches.py --check BASELINE SWITCH``. Every
scenario is deadline-checked on its own; one that does not fit is skipped and reported (it runs
again next Sunday). Informational: the outcome is reported, it never changes the night's status.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gate_orchestrator.candidate import candidate_argv
from gate_orchestrator.gate_run import (
    CANDIDATE_PORT,
    Runner,
    candidate_env,
    docker_run_env,
    ip_argv,
    run_config,
)
from gate_orchestrator.window import phase_check

SCRIPT = Path("experiments") / "noise" / "cause_switches.py"
RAG_PREFIX = "apps/rag-demo/"
MINUTES_PER_SCENARIO = 30.0


@dataclass(frozen=True)
class PlannedRun:
    """One line of ``cause_switches.py --plan`` (the fields the orchestrator needs)."""

    scenario: str
    role: str
    rag_config: str
    argv: tuple[str, ...]
    env: Mapping[str, str]


def parse_plan(text: str) -> list[PlannedRun]:
    """The JSON lines of ``--plan``.

    Raises:
        ValueError: a line is not a planned run, or a config path leaves ``apps/rag-demo/configs``.
    """
    runs = []
    for line in text.splitlines():
        if not line.strip().startswith("{"):
            continue
        data = json.loads(line)
        rag = str(data["rag_config"])
        if not rag.startswith(RAG_PREFIX + "configs/") or ".." in rag:
            msg = f"planned rag config outside apps/rag-demo/configs: {rag!r}"
            raise ValueError(msg)
        runs.append(
            PlannedRun(
                scenario=str(data["scenario"]),
                role=str(data["role"]),
                rag_config=rag,
                argv=tuple(str(a) for a in data["argv"]),
                env={str(k): str(v) for k, v in dict(data.get("env") or {}).items()},
            )
        )
    return runs


def container_config(rag_config: str) -> str:
    """``apps/rag-demo/configs/x.yaml`` → the path inside the image, ``/app/configs/x.yaml``."""
    return "/app/" + rag_config.removeprefix(RAG_PREFIX)


def run_argv(planned: PlannedRun, config: Path) -> list[str]:
    """The planned argv with ``--config`` replaced by the per-run config (target URL set)."""
    argv = list(planned.argv)
    argv[argv.index("--config") + 1] = str(config)
    return argv


def plan_argv(main_dir: Path, out: Path) -> list[str]:
    """``python experiments/noise/cause_switches.py --plan OUT --scenarios all``."""
    return ["python", str(main_dir / SCRIPT), "--plan", str(out), "--scenarios", "all"]


def check_argv(main_dir: Path, scenario: str, baseline: Path, switch: Path) -> list[str]:
    """``python experiments/noise/cause_switches.py --check BASELINE SWITCH --scenarios NAME``."""
    script = str(main_dir / SCRIPT)
    return ["python", script, "--check", str(baseline), str(switch), "--scenarios", scenario]


@dataclass
class CausePhase:
    """Runs the planned scenarios; ``lines`` collects the report."""

    run: Runner
    image_ref: str
    main_dir: Path
    work: Path
    env: Mapping[str, str]
    now: Callable[[], datetime]
    deadline: datetime
    lines: list[str]

    def _serve_and_run(self, planned: PlannedRun) -> Path | None:
        name = f"cause-{planned.scenario}-{planned.role}".replace("_", "-")
        cenv = candidate_env(self.env, rag_config=container_config(planned.rag_config))
        argv = candidate_argv(self.image_ref, name=name, job_label=name, env=cenv)
        try:
            if self.run(argv, docker_run_env(self.env, cenv))[0] != 0:
                return None
            code, ip = self.run(ip_argv(name), self.env)
            if code != 0:
                return None
            url = f"http://{ip.strip()}:{CANDIDATE_PORT}"
            src = self.main_dir / planned.argv[planned.argv.index("--config") + 1]
            config = run_config(src, self.work / f"{name}.yaml", url)
            code, out = self.run(run_argv(planned, config), {**self.env, **planned.env})
            lines = out.strip().splitlines()
            return Path(lines[-1]) if code == 0 and lines else None
        finally:
            self.run(["docker", "rm", "-f", name], self.env)

    def scenario(self, name: str, runs: Sequence[PlannedRun]) -> None:
        """Baseline and switch of one scenario, then the check; one report line."""
        if phase_check(self.now(), self.deadline, f"cause-switches {name}", MINUTES_PER_SCENARIO):
            self.lines.append(f"{name}: skipped: window (runs next Sunday)")
            return
        dirs = {r.role: self._serve_and_run(r) for r in runs}
        base, switch = dirs.get("baseline"), dirs.get("switch")
        if base is None or switch is None:
            self.lines.append(f"{name}: not checked (a run failed)")
            return
        code, _ = self.run(check_argv(self.main_dir, name, base, switch), self.env)
        self.lines.append(f"{name}: {'ok' if code == 0 else 'FAILED'}")

    def __call__(self) -> None:
        """Plan, then every scenario in plan order (informational, never raises on a failure)."""
        code, out = self.run(plan_argv(self.main_dir, self.work / "cause"), self.env)
        if code != 0:
            self.lines.append(f"cause-switches: plan failed (exit {code})")
            return
        runs = parse_plan(out)
        for name in dict.fromkeys(r.scenario for r in runs):
            self.scenario(name, [r for r in runs if r.scenario == name])
