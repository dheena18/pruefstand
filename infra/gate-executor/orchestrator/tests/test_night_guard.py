"""night-guard (N4.3, P2.1, A12-03, D1095): which cron fired, both DST seasons, stdlib only."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from gate_orchestrator.cli import main
from gate_orchestrator.night_guard import GuardError, decide, fired_instant, github_output

ORCH = Path(__file__).resolve().parents[1]
SUMMER, WINTER = "7 20 * * *", "7 21 * * *"


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("schedule", "now", "run", "deadline"),
    [
        (SUMMER, _at(2026, 7, 1, 20, 8), True, "2026-07-02T06:00:00+02:00"),
        (WINTER, _at(2026, 7, 1, 21, 8), False, "2026-07-02T06:00:00+02:00"),
        (WINTER, _at(2026, 11, 16, 21, 8), True, "2026-11-17T06:00:00+01:00"),
        (SUMMER, _at(2026, 11, 16, 20, 8), False, "2026-11-17T06:00:00+01:00"),
        # DST end 2026-10-25 03:00 CEST -> 02:00 CET: the night of 24/25 still fires in CEST
        (SUMMER, _at(2026, 10, 24, 20, 7), True, "2026-10-25T06:00:00+01:00"),
        (WINTER, _at(2026, 10, 25, 21, 7), True, "2026-10-26T06:00:00+01:00"),
        # DST start 2026-03-29: the evening of the 29th is CEST
        (SUMMER, _at(2026, 3, 29, 20, 7), True, "2026-03-30T06:00:00+02:00"),
        (WINTER, _at(2026, 3, 28, 21, 7), True, "2026-03-29T06:00:00+02:00"),
    ],
)
def test_season_decides_by_the_cron_that_fired(
    schedule: str, now: datetime, *, run: bool, deadline: str
) -> None:
    assert decide("schedule", schedule, now) == (run, deadline)


def test_a_late_start_keeps_its_night_and_deadline() -> None:
    # fired 22:07 Berlin, the busy runner starts the guard at 01:30 Berlin: still that night
    assert decide("schedule", WINTER, _at(2026, 11, 17, 0, 30)) == (
        True,
        "2026-11-17T06:00:00+01:00",
    )
    assert fired_instant(WINTER, _at(2026, 11, 17, 0, 30)) == _at(2026, 11, 16, 21, 7)


def test_dispatch_always_runs_with_tonights_or_the_override_deadline() -> None:
    now = _at(2026, 11, 16, 22, 0)  # 23:00 Berlin
    assert decide("workflow_dispatch", "", now) == (True, "2026-11-17T06:00:00+01:00")
    assert decide("workflow_dispatch", "", now, "23:30") == (True, "2026-11-16T23:30:00+01:00")
    assert decide("workflow_dispatch", "", now, "22:30") == (True, "2026-11-17T22:30:00+01:00")


@pytest.mark.parametrize(
    ("event", "schedule", "override"),
    [("push", "", ""), ("schedule", "7 22 * * *", ""), ("workflow_dispatch", "", "25:00")],
)
def test_bad_inputs_are_refused(event: str, schedule: str, override: str) -> None:
    with pytest.raises(GuardError):
        decide(event, schedule, _at(2026, 11, 16, 21, 8), override)


def test_output_lines_and_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert github_output(run=False, deadline="x") == "run=false\ndeadline=x\n"
    assert main(["night-guard", "--event", "workflow_dispatch"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "run=true"
    assert out[1].startswith("deadline=")
    assert main(["night-guard", "--event", "schedule", "--schedule", "0 0 * * *"]) == 2


def test_hosted_guard_needs_only_the_standard_library() -> None:
    # -S: no site-packages, so pydantic and pruefstand cannot be imported (as on the hosted runner)
    code = (
        f"import sys; sys.path.insert(0, {str(ORCH)!r}); from gate_orchestrator.cli import main; "
        "sys.exit(main(['night-guard', '--event', 'schedule', '--schedule', '7 21 * * *']))"
    )
    done = subprocess.run(  # noqa: S603  (fixed argv: this interpreter)
        [sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("run=")
