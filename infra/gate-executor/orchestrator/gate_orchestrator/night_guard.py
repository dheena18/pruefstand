"""The hosted ``guard`` job of ``nightly.yml`` (N4.3, P2.1, A12-03, D1095): stdlib only.

It decides by WHICH cron fired, never by the start time: ``7 20 * * *`` runs only when Europe/Berlin
is on summer time (CEST, UTC+2) at the fired instant, ``7 21 * * *`` only on winter time (CET,
UTC+1), so exactly one of the two fires per night. The fired instant is the latest instant <= now
that matches the cron, so a nightly delayed by a busy runner or a late GitHub cron still runs and
keeps its night's deadline. ``workflow_dispatch`` always runs; its deadline is 06:00 Berlin of the
night containing the dispatch, or the ``HH:MM`` drill override (the next such Berlin time),
never later than that 06:00 (D290: a drill can shorten the night, not extend it into the day).
"""

import re
from datetime import UTC, datetime, time, timedelta

from gate_orchestrator.window import BERLIN, night_deadline

CRONS = {"7 20 * * *": timedelta(hours=2), "7 21 * * *": timedelta(hours=1)}
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


class GuardError(ValueError):
    """Unknown event, unknown cron or a malformed deadline override."""


def fired_instant(schedule: str, now: datetime) -> datetime:
    """The latest instant <= ``now`` matching ``schedule`` (one of :data:`CRONS`), in UTC.

    >>> fired_instant("7 21 * * *", datetime(2026, 11, 16, 23, 30, tzinfo=UTC)).isoformat()
    '2026-11-16T21:07:00+00:00'

    Raises:
        GuardError: not one of the two nightly crons.
    """
    if schedule not in CRONS:
        msg = f"unknown nightly schedule {schedule!r}"
        raise GuardError(msg)
    minute, hour = (int(f) for f in schedule.split()[:2])
    now_utc = now.astimezone(UTC)
    fired = datetime.combine(now_utc.date(), time(hour, minute), tzinfo=UTC)
    return fired if fired <= now_utc else fired - timedelta(days=1)


def _override(deadline_input: str, now: datetime) -> datetime:
    match = _HHMM.fullmatch(deadline_input)
    if match is None:
        msg = f"deadline override must be HH:MM, got {deadline_input!r}"
        raise GuardError(msg)
    local = now.astimezone(BERLIN)
    wanted = time(int(match.group(1)), int(match.group(2)))
    candidate = datetime.combine(local.date(), wanted, tzinfo=BERLIN)
    return candidate if candidate > local else candidate + timedelta(days=1)


def decide(event: str, schedule: str, now: datetime, deadline_input: str = "") -> tuple[bool, str]:
    """``(run, deadline ISO)`` for the guard's outputs.

    >>> decide("schedule", "7 21 * * *", datetime(2026, 11, 16, 21, 8, tzinfo=UTC))
    (True, '2026-11-17T06:00:00+01:00')
    >>> decide("schedule", "7 20 * * *", datetime(2026, 11, 16, 20, 8, tzinfo=UTC))[0]
    False

    Raises:
        GuardError: unknown event or cron, or a malformed override.
    """
    if now.tzinfo is None:
        msg = "now must be timezone-aware"
        raise GuardError(msg)
    if event == "workflow_dispatch":
        deadline = night_deadline(now)
        if deadline_input:  # a drill may shorten the night, never extend it past 06:00 (D290)
            deadline = min(deadline, _override(deadline_input, now))
        return True, deadline.isoformat()
    if event != "schedule":
        msg = f"unknown event {event!r}"
        raise GuardError(msg)
    fired = fired_instant(schedule, now)
    offset = fired.astimezone(BERLIN).utcoffset()
    return offset == CRONS[schedule], night_deadline(fired).isoformat()


def github_output(*, run: bool, deadline: str) -> str:
    """The two ``$GITHUB_OUTPUT`` lines."""
    return f"run={'true' if run else 'false'}\ndeadline={deadline}\n"
