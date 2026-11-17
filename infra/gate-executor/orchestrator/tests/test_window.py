"""Nightly window, deadline, phase budget, block rotation (N4.3, D290, D299); injected clock."""

from datetime import UTC, datetime, timedelta

import pytest
from gate_orchestrator.window import (
    baseline_refs,
    block_of,
    in_window,
    late_start,
    night_deadline,
    phase_check,
    updates_last_nightly_at,
)


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "inside"),
    [
        (_utc(2026, 11, 10, 21, 0), True),  # 22:00 Berlin (CET)
        (_utc(2026, 11, 10, 20, 59), False),
        (_utc(2026, 11, 11, 4, 59), True),  # 05:59 Berlin
        (_utc(2026, 11, 11, 5, 0), False),  # 06:00 Berlin
        (_utc(2026, 7, 10, 20, 7), True),  # 22:07 Berlin (CEST)
        (_utc(2026, 7, 10, 12, 0), False),
    ],
)
def test_in_window(moment: datetime, inside: bool) -> None:  # noqa: FBT001 - parametrized
    assert in_window(moment) is inside


@pytest.mark.parametrize(
    ("fired", "deadline"),
    [
        (_utc(2026, 11, 10, 21, 7), "2026-11-11T06:00:00+01:00"),  # winter cron 7 21 * * *
        (_utc(2026, 7, 10, 20, 7), "2026-07-11T06:00:00+02:00"),  # summer cron 7 20 * * *
        (_utc(2026, 11, 11, 1, 0), "2026-11-11T06:00:00+01:00"),  # dispatched after midnight
        (_utc(2026, 3, 28, 21, 7), "2026-03-29T06:00:00+02:00"),  # DST starts during the night
        (_utc(2026, 10, 24, 20, 7), "2026-10-25T06:00:00+01:00"),  # DST ends during the night
    ],
)
def test_night_deadline_is_the_next_0600_berlin(fired: datetime, deadline: str) -> None:
    assert night_deadline(fired).isoformat() == deadline


def test_naive_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        in_window(datetime(2026, 11, 10, 22, 0))  # noqa: DTZ001 - the naive input under test


def test_late_start() -> None:
    deadline = night_deadline(_utc(2026, 11, 10, 21, 7))
    assert late_start(deadline - timedelta(minutes=1), deadline) is None
    assert late_start(deadline, deadline) == "window_exceeded: late start"
    assert late_start(deadline + timedelta(hours=3), deadline) == "window_exceeded: late start"


def test_phase_needing_90_min_with_60_left_is_not_started() -> None:
    deadline = night_deadline(_utc(2026, 11, 10, 21, 7))
    now = deadline - timedelta(minutes=60)
    assert phase_check(now, deadline, "nightly-gate", 90) == "window_exceeded: nightly-gate"
    assert phase_check(now, deadline, "drift", 60) is None
    assert phase_check(now, deadline, "drift", 59.5) is None
    with pytest.raises(ValueError, match="planned_minutes"):
        phase_check(now, deadline, "drift", -1)


@pytest.mark.parametrize(
    ("counter", "refs"),
    [
        (0, ("nightly-b0", "release-b0")),
        (4, ("nightly-b1", "release-b1")),
        (5, ("nightly-b2", "release-b2")),
        (6, ("nightly-b0", "release-b0")),
    ],
)
def test_block_rotation(counter: int, refs: tuple[str, str]) -> None:
    assert baseline_refs(counter) == refs
    assert block_of(counter) == int(refs[0][-1])


def test_negative_counter_is_refused() -> None:
    with pytest.raises(ValueError, match="counter"):
        block_of(-1)


@pytest.mark.parametrize(
    ("status", "updates"),
    [
        ("ok", True),
        ("failed", True),
        ("aborted: window_exceeded", False),
        ("skipped: maintenance", False),
        ("skipped: runner busy", False),
        ("skipped: preflight data root unavailable", False),
    ],
)
def test_last_nightly_at_changes_only_for_ok_or_failed(status: str, updates: bool) -> None:  # noqa: FBT001
    assert updates_last_nightly_at(status) is updates
