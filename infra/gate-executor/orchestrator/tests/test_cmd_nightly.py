"""nightly phases (N4.3, P2.1, P4.4, A13-M3, D1099): deadlines, statuses, argv, the gate phase."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from gate_orchestrator.cmd_nightly import final_status, lock_budget_s, night_status, phases
from gate_orchestrator.heartbeat import check_nightly_status
from gate_orchestrator.models import Job
from gate_orchestrator.nightly_run import (
    PLANNED_MINUTES,
    NightlyRun,
    nightly_gate_argvs,
    nightly_run_argv,
)
from orch_testkit import SpyPoster

DEADLINE = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)  # 06:00 Berlin
MAIN_CONFIG = Path(__file__).resolve().parents[4] / "pruefstand.yaml"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", ("success", "nightly ok")),
        ("failed", ("failure", "nightly failed")),
        ("skipped: maintenance", ("success", "skipped: maintenance")),
        ("aborted: window_exceeded", ("error", "nightly aborted: window_exceeded")),
        ("skipped: runner busy", ("error", "nightly skipped: runner busy")),
    ],
)
def test_final_status(status: str, expected: tuple[str, str]) -> None:
    assert final_status(status) == expected


@pytest.mark.parametrize(
    "result", ["ok", "failed", "infra error: ollama_down: x", "image verification failed: x"]
)
def test_every_gate_result_maps_to_the_a13_m3_vocabulary(result: str) -> None:
    assert check_nightly_status(night_status(result)) == night_status(result)


def test_lock_budget_leaves_room_for_the_phases() -> None:
    planned = sum(PLANNED_MINUTES.values())
    assert lock_budget_s(DEADLINE - timedelta(hours=8), DEADLINE) == pytest.approx(
        (8 * 60 - planned) * 60
    )
    assert lock_budget_s(DEADLINE - timedelta(hours=1), DEADLINE) == 0.0


def test_phases_stop_at_the_first_that_does_not_fit() -> None:
    ran: list[str] = []
    clock = [DEADLINE - timedelta(minutes=370)]

    def step(name: str) -> tuple[str, object]:
        def run() -> None:
            ran.append(name)
            clock[0] += timedelta(minutes=10)

        return name, run

    steps = [step("switch-mode"), step("judge-drift"), step("nightly-gate")]
    result = phases(lambda: clock[0], DEADLINE, steps)  # type: ignore[arg-type]  # (name, callable) pairs
    assert ran == ["switch-mode", "judge-drift"]
    assert result == "window_exceeded: nightly-gate"


def test_argv() -> None:
    run = nightly_run_argv(Path("c.yaml"), Path("runs"))
    assert run[-6:] == ["--split", "full", "--stratum", "all", "--block", "auto"]
    assert "--tier" in run
    assert run[run.index("--tier") + 1] == "nightly"
    gate, drift = nightly_gate_argvs(Path("runs/r"), Path("c.yaml"), 2)
    assert gate[-2:] == ["--ref", "nightly-b2"]
    assert drift[-2:] == ["--ref", "release-b2"]


def _nightly(
    tmp: Path, gate_exit: int, infra: str | None = None
) -> tuple[NightlyRun, list[list[str]], list[Mapping[str, str]]]:
    calls: list[list[str]] = []
    envs: list[Mapping[str, str]] = []

    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        calls.append(args)
        envs.append(env)
        if args[:2] == ["pruefstand", "run"]:
            out = tmp / "night"
            out.mkdir(exist_ok=True)
            (out / "run.json").write_text(
                json.dumps({"block": 1, "infra_error": infra}), encoding="utf-8"
            )
            return 0, f"{out}\n"
        if args[:2] == ["pruefstand", "gate"]:
            return (gate_exit if args[-1] == "nightly-b1" else 0), ""
        return 0, ""

    attempt = NightlyRun(
        job=Job(kind="gate", sha="a" * 40, pr_number=None, tier="nightly"),
        digest="sha256:" + "b" * 64,
        run=run,
        poster=SpyPoster(),
        statuses=lambda _sha: [],
        main_config=MAIN_CONFIG,
        work=tmp,
        env={},
        counter=4,
    )
    return attempt, calls, envs


@pytest.mark.parametrize(("gate_exit", "result"), [(0, "ok"), (1, "failed")])
def test_the_gate_phase_gates_block_k_and_measures_drift(
    tmp_path: Path, gate_exit: int, result: str
) -> None:
    attempt, calls, envs = _nightly(tmp_path, gate_exit)
    assert attempt._run_and_gate("http://10.0.0.5:8000") is None
    assert attempt.result == result
    gates = [c[-1] for c in calls if c[:2] == ["pruefstand", "gate"]]
    assert gates == ["nightly-b1", "release-b1"]
    run_env = envs[[c[:2] for c in calls].index(["pruefstand", "run"])]
    assert run_env["PRUEFSTAND_NIGHTLY_COUNTER"] == "4"


def test_an_infra_error_of_the_run_is_returned_and_nothing_is_gated(tmp_path: Path) -> None:
    attempt, calls, _ = _nightly(tmp_path, 0, infra="ollama_down: gpu0")
    assert attempt._run_and_gate("http://10.0.0.5:8000") == "ollama_down: gpu0"
    assert not any(c[:2] == ["pruefstand", "gate"] for c in calls)


def test_the_night_is_written_where_promote_poll_looks(tmp_path: Path) -> None:
    # promote-poll scans $PRUEFSTAND_HOME/runs/; a night written to the job's temp dir is lost
    attempt, calls, _ = _nightly(tmp_path, 0)
    attempt.runs_dir = tmp_path / "home" / "runs"
    attempt._run_and_gate("http://10.0.0.5:8000")
    run = next(c for c in calls if c[:2] == ["pruefstand", "run"])
    assert run[run.index("--out") + 1] == str(tmp_path / "home" / "runs")
