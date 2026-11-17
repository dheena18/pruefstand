"""The nightly through ``run_nightly`` with a scripted host (review #236): every stated rule."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from gate_orchestrator import heartbeat_store
from gate_orchestrator.index_job import Aliases
from gate_orchestrator.infra import InfraError
from gate_orchestrator.nightly_flow import NightDeps, make_runner, run_nightly
from gate_orchestrator.nightly_run import PLANNED_MINUTES, gate_failed
from orch_testkit import SpyPoster

REPO = Path(__file__).resolve().parents[4]
HEAD = "a" * 40
DEADLINE = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)  # 06:00 Berlin
START = DEADLINE - timedelta(hours=8)
IMAGE = {"context": "pruefstand/image", "state": "success", "description": "sha256:" + "b" * 64}


class _Reader:
    def branch_head(self, branch: str) -> str | None:
        return HEAD

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        return [IMAGE]


@dataclass
class Host:
    """Scripted answers of the commands a night runs."""

    gate_exit: int = 0
    judge_drift_exit: int = 0
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        self.calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": HEAD})
        if args[:2] == ["docker", "inspect"]:
            return 0, "10.231.0.5\n"
        if args[:2] == ["pruefstand", "judge-drift"]:
            return self.judge_drift_exit, ""
        if args[:2] == ["pruefstand", "run"]:
            out = Path(args[args.index("--out") + 1]) / f"night{len(self.calls)}"
            out.mkdir(parents=True)
            (out / "run.json").write_text(
                json.dumps({"block": 1, "infra_error": None}), encoding="utf-8"
            )
            return 0, f"{out}\n"
        if args[:2] == ["pruefstand", "gate"] and args[-1] == "nightly-b1":
            return self.gate_exit, ""
        return 0, ""

    def has(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == list(prefix) for c in self.calls)


@pytest.fixture
def pushed(monkeypatch: pytest.MonkeyPatch) -> list[Mapping[str, str]]:
    sent: list[Mapping[str, str]] = []

    def push(repo: str, payload: Mapping[str, str]) -> str:
        sent.append(dict(payload))
        return "sha"

    monkeypatch.setattr(heartbeat_store, "push_heartbeat", push)
    return sent


def _night(
    tmp: Path, host: Host, *, now: datetime = START, aliases: Aliases | None = None
) -> tuple[SpyPoster, Path]:
    home = tmp / "home"
    poster = SpyPoster()
    deps = NightDeps(
        env={"PRUEFSTAND_HOME": str(home), "PRUEFSTAND_MAIN_DIR": str(REPO)},
        reader=_Reader(),
        poster=poster,
        run=host,
        lock_dir=tmp / "lock",
        now=lambda: now,
        aliases=aliases,
    )
    deps.lock_dir.mkdir(exist_ok=True)
    assert run_nightly(DEADLINE, tmp / "report", deps) == 0
    return poster, home


def _counter(home: Path) -> str:
    path = home / "state" / "nightly_counter"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "0"


def test_a_good_night_writes_its_run_to_home_runs_and_advances_the_counter(
    tmp_path: Path, pushed: list[Mapping[str, str]]
) -> None:
    host = Host()
    poster, home = _night(tmp_path, host)
    run = next(c for c in host.calls if c[:2] == ["pruefstand", "run"])
    assert run[run.index("--out") + 1] == str(home / "runs")  # where promote-poll looks
    assert host.has("pruefstand", "judge-drift", "--judge")
    assert host.calls[-1][-1] == "day"  # switch-mode.sh day ends the night
    assert _counter(home) == "1"
    assert poster.calls[-1][:4] == ("post_status", HEAD, "success", "nightly ok")
    assert pushed[-1]["last_nightly_status"] == "ok"


def test_a_failing_judge_drift_still_switches_back_to_day_and_keeps_the_counter(
    tmp_path: Path, pushed: list[Mapping[str, str]]
) -> None:
    host = Host(judge_drift_exit=1)
    poster, home = _night(tmp_path, host)
    assert host.calls[-1][-1] == "day"
    assert not host.has("pruefstand", "run")
    assert _counter(home) == "0"
    assert pushed[-1]["last_nightly_status"].startswith("skipped: preflight pruefstand judge-drift")
    assert poster.calls[-1][2] == "error"


@pytest.mark.parametrize(("gate_exit", "status", "counter"), [(0, "ok", "1"), (1, "failed", "1")])
def test_the_gate_decides_the_night(
    tmp_path: Path, pushed: list[Mapping[str, str]], gate_exit: int, status: str, counter: str
) -> None:
    _, home = _night(tmp_path, Host(gate_exit=gate_exit))
    assert pushed[-1]["last_nightly_status"] == status
    assert _counter(home) == counter


@pytest.mark.parametrize("gate_exit", [2, 3])
def test_a_crashed_gate_is_never_an_ok_night(
    tmp_path: Path, pushed: list[Mapping[str, str]], gate_exit: int
) -> None:
    poster, home = _night(tmp_path, Host(gate_exit=gate_exit))
    assert pushed[-1]["last_nightly_status"].startswith(
        "skipped: preflight infra error: gate_failed"
    )
    assert _counter(home) == "0"
    assert poster.calls[-1][2] == "error"


@pytest.mark.parametrize(("code", "failed"), [(0, False), (1, True)])
def test_gate_exit_mapping(code: int, *, failed: bool) -> None:
    assert gate_failed(code) is failed


@pytest.mark.parametrize("code", [2, 3, -9])
def test_other_gate_exits_are_infra_errors(code: int) -> None:
    with pytest.raises(InfraError, match="gate_failed"):
        gate_failed(code)


def test_maintenance_ends_the_night_before_the_lock(
    tmp_path: Path, pushed: list[Mapping[str, str]]
) -> None:
    (tmp_path / "lock").mkdir()
    (tmp_path / "lock" / "MAINTENANCE").write_text("", encoding="utf-8")
    host = Host()
    poster, _ = _night(tmp_path, host)
    assert host.calls == []
    assert pushed[-1]["last_nightly_status"] == "skipped: maintenance"
    assert poster.calls[-1][2:4] == ("success", "skipped: maintenance")


def test_a_start_after_the_deadline_runs_nothing(
    tmp_path: Path, pushed: list[Mapping[str, str]]
) -> None:
    host = Host()
    _night(tmp_path, host, now=DEADLINE + timedelta(minutes=20))
    assert host.calls == []
    assert pushed[-1]["last_nightly_status"] == "aborted: window_exceeded"


def test_the_nightly_run_may_use_the_time_left_before_the_deadline() -> None:
    seen: list[tuple[str, float]] = []

    def fake_subprocess(
        argv: Sequence[str], env: Mapping[str, str], timeout: float
    ) -> tuple[int, str]:
        seen.append((argv[1], timeout))
        return 0, ""

    run = make_runner(DEADLINE, lambda: START, fake_subprocess)
    run(["pruefstand", "run", "--tier", "nightly"], {})
    run(["docker", "pull", "x"], {})
    assert seen[0][1] >= PLANNED_MINUTES["nightly-gate"] * 60  # never the PR runner's 100 min
    assert seen[1][1] == 600


def test_the_night_checks_the_shared_index_through_its_deps(
    tmp_path: Path, pushed: list[Mapping[str, str]]
) -> None:
    # review #259: nightly_flow must hand NightDeps.aliases to the attempt
    host = Host()
    _, home = _night(tmp_path, host, aliases=lambda env: set())
    assert "index_missing" in pushed[-1]["last_nightly_status"]
    assert not host.has("pruefstand", "run")
    assert _counter(home) == "0"
