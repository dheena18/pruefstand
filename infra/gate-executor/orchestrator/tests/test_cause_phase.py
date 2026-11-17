"""Weekly cause-switches phase (T6.3 S4, Y4.3, AI12-10, D1027): the real plan, scripted host."""

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from gate_orchestrator.cause_phase import (
    CausePhase,
    container_config,
    parse_plan,
    plan_argv,
    run_argv,
)
from gate_orchestrator.cmd_nightly import causes_tonight

REPO = Path(__file__).resolve().parents[4]
DEADLINE = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


def _real_plan(out: Path) -> str:
    argv = [sys.executable, *plan_argv(REPO, out)[1:]]
    done = subprocess.run(  # noqa: S603  (fixed argv: the repo's own T6.3 script)
        argv, capture_output=True, text=True, timeout=120, check=True, cwd=REPO
    )
    return done.stdout


def test_the_real_plan_parses_into_two_runs_per_scenario(tmp_path: Path) -> None:
    runs = parse_plan(_real_plan(tmp_path))
    scenarios = list(dict.fromkeys(r.scenario for r in runs))
    assert len(scenarios) == 5
    assert len(runs) == 10
    for run in runs:
        assert (REPO / run.rag_config).is_file()
        assert container_config(run.rag_config).startswith("/app/configs/")
        assert (REPO / run.argv[run.argv.index("--config") + 1]).is_file()
    refusal = [r for r in runs if r.scenario == "refusal_policy"]
    assert all("PRUEFSTAND_JUDGE_MODE" not in r.env for r in refusal)  # judged on purpose (AI12-10)
    assert all(r.env.get("PRUEFSTAND_JUDGE_MODE") == "skipped" for r in runs if r not in refusal)


def test_run_argv_swaps_only_the_config(tmp_path: Path) -> None:
    run = parse_plan(_real_plan(tmp_path))[0]
    argv = run_argv(run, tmp_path / "x.yaml")
    assert argv[argv.index("--config") + 1] == str(tmp_path / "x.yaml")
    assert len(argv) == len(run.argv)


@pytest.mark.parametrize("rag", ["apps/rag-demo/configs/../../../etc/x.yaml", "/etc/passwd"])
def test_a_rag_config_outside_the_configs_is_refused(rag: str) -> None:
    line = json.dumps(
        {"scenario": "x", "role": "baseline", "rag_config": rag, "argv": [], "env": {}}
    )
    with pytest.raises(ValueError, match="outside"):
        parse_plan(line)


def _phase(tmp: Path, *, check_exit: int, now: datetime) -> tuple[CausePhase, list[list[str]]]:
    plan_text = _real_plan(tmp / "plan")
    calls: list[list[str]] = []

    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        calls.append(args)
        if "--plan" in args:
            return 0, plan_text
        if args[:2] == ["docker", "inspect"]:
            return 0, "10.231.0.9\n"
        if args[:2] == ["pruefstand", "run"]:
            out = Path(args[args.index("--out") + 1]) / "r"
            out.mkdir(parents=True, exist_ok=True)
            return 0, f"{out}\n"
        if "--check" in args:
            return check_exit, ""
        return 0, ""

    phase = CausePhase(
        run=run,
        image_ref="ghcr.io/dheena18/rag-demo@sha256:" + "b" * 64,
        main_dir=REPO,
        work=tmp,
        env={"QDRANT_READ_ONLY_API_KEY": "ro"},
        now=lambda: now,
        deadline=DEADLINE,
        lines=[],
    )
    return phase, calls


@pytest.mark.parametrize(("check_exit", "word"), [(0, "ok"), (1, "FAILED")])
def test_every_scenario_runs_baseline_and_switch_then_the_check(
    tmp_path: Path, check_exit: int, word: str
) -> None:
    phase, calls = _phase(tmp_path, check_exit=check_exit, now=DEADLINE - timedelta(hours=6))
    phase()
    assert len(phase.lines) == 5
    assert all(line.endswith(word) for line in phase.lines)
    runs = [c for c in calls if c[:2] == ["docker", "run"]]
    assert len(runs) == 10
    assert sum(c[:3] == ["docker", "rm", "-f"] for c in calls) == 10
    configs = [
        c[c.index("RAG_CONFIG") - 1 : c.index("RAG_CONFIG") + 1] for c in runs if "RAG_CONFIG" in c
    ]
    assert configs == [["--env", "RAG_CONFIG"]] * 10  # value passed by name, never on the line
    assert sum("--check" in c for c in calls) == 5


def test_a_scenario_that_no_longer_fits_is_skipped_and_reported(tmp_path: Path) -> None:
    phase, calls = _phase(tmp_path, check_exit=0, now=DEADLINE - timedelta(minutes=20))
    phase()
    assert all("skipped: window" in line for line in phase.lines)
    assert not any(c[:2] == ["docker", "run"] for c in calls)


@pytest.mark.parametrize(
    ("mode", "started", "expected"),
    [
        ("skip", datetime(2026, 11, 15, 21, 7, tzinfo=UTC), False),  # a Sunday night
        ("auto", datetime(2026, 11, 15, 21, 7, tzinfo=UTC), True),
        ("auto", datetime(2026, 11, 16, 21, 7, tzinfo=UTC), False),  # a Monday night
        ("force", datetime(2026, 11, 16, 21, 7, tzinfo=UTC), True),
    ],
)
def test_causes_tonight(mode: str, started: datetime, *, expected: bool) -> None:
    assert causes_tonight(mode, started) is expected
