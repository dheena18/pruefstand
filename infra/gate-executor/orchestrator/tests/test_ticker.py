"""Heartbeat during a dispatch (Y5.1, D225, D1031): immediate tick, refresh, stop, never fatal."""

import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from gate_orchestrator.gate_job import Attempt, run_gate_job
from gate_orchestrator.models import Job
from gate_orchestrator.ticker import ticking
from orch_testkit import SpyPoster

from pruefstand.core.errors import PruefstandError

REPO = Path(__file__).resolve().parents[4]
SHA = "a" * 40


def test_ticks_at_once_then_every_interval_and_stops_with_the_block() -> None:
    ticks: list[int] = []
    three = threading.Event()

    def tick() -> None:
        ticks.append(1)
        if len(ticks) >= 3:
            three.set()

    with ticking(tick, interval_s=0.01):
        assert three.wait(5)
    seen = len(ticks)
    threading.Event().wait(0.05)
    assert len(ticks) == seen  # stopped


def test_a_failing_tick_never_stops_the_job() -> None:
    calls: list[int] = []

    def tick() -> None:
        calls.append(1)
        msg = "github down"
        raise PruefstandError(msg)

    with ticking(tick, interval_s=0.01):
        threading.Event().wait(0.05)
    assert len(calls) >= 2


def test_a_dispatch_reports_its_job_health_and_result(tmp_path: Path) -> None:
    beats: list[Mapping[str, str]] = []

    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        if list(argv[:3]) == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": SHA})
        if list(argv[:2]) == ["pruefstand", "run"]:
            run_dir = tmp_path / "r1"
            run_dir.mkdir(exist_ok=True)
            (run_dir / "run.json").write_text(json.dumps({"infra_error": None}), encoding="utf-8")
            gate = {"status": "pass", "candidate_run_id": "r1"}
            (run_dir / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
            return 0, f"{run_dir}\n"
        return 0, ""

    attempt = Attempt(
        job=Job(kind="gate", sha=SHA, pr_number=7, tier="pr"),
        digest="sha256:" + "b" * 64,
        run=run,
        poster=SpyPoster(),
        statuses=lambda _sha: [],
        main_config=REPO / "pruefstand.yaml",
        work=tmp_path,
    )
    result = run_gate_job(
        attempt, health_sh=tmp_path / "health.sh", lock_dir=tmp_path, beat=beats.append
    )
    assert result == "pass"
    assert beats[0]["last_job"] == "pr 7 aaaaaaa"
    assert "tunnel_ok" not in beats[0]  # before the preflight nothing is claimed
    assert beats[-1]["last_result"] == "pass"
    assert beats[-1]["tunnel_ok"] == "true"
    assert beats[-1]["data_root_ok_false_since"] == ""
