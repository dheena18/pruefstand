"""Nightly window rules (N4.3, D290, D298, D299): deadline, per-phase budget, block rotation.

Pure; the clock is injected (``now`` is an aware ``datetime``). The night window is 22:00–06:00
Europe/Berlin; the deadline of a night is the first 06:00 Berlin after the fired schedule instant.
A job that starts at or after the deadline ends with ``window_exceeded: late start``; a phase whose
planned minutes do not fit before the deadline is not started (``window_exceeded: <phase>``, no
retry, nothing promoted). Block ``k = nightly_counter mod 3`` gates against ``nightly-b<k>`` and
measures drift against ``release-b<k>`` (D305).
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
WINDOW_START = time(22, 0)
WINDOW_END = time(6, 0)
BLOCKS = 3
COMPLETED = frozenset({"ok", "failed"})


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    return moment.astimezone(BERLIN)


def in_window(now: datetime) -> bool:
    """True between 22:00 and 06:00 Europe/Berlin (start inclusive, end exclusive).

    Raises:
        ValueError: ``now`` is naive.
    """
    local = _aware(now).time()
    return local >= WINDOW_START or local < WINDOW_END


def night_deadline(fired_at: datetime) -> datetime:
    """The first 06:00 Europe/Berlin strictly after ``fired_at`` (DST-safe wall-clock time).

    >>> from datetime import timezone
    >>> night_deadline(datetime(2026, 11, 10, 21, 7, tzinfo=timezone.utc)).isoformat()
    '2026-11-11T06:00:00+01:00'

    Raises:
        ValueError: ``fired_at`` is naive.
    """
    local = _aware(fired_at)
    candidate = datetime.combine(local.date(), WINDOW_END, tzinfo=BERLIN)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), WINDOW_END, tzinfo=BERLIN)
    return candidate


def late_start(now: datetime, deadline: datetime) -> str | None:
    """``"window_exceeded: late start"`` when starting at or after the deadline, else ``None``."""
    return "window_exceeded: late start" if _aware(now) >= _aware(deadline) else None


def phase_check(
    now: datetime, deadline: datetime, phase: str, planned_minutes: float
) -> str | None:
    """``"window_exceeded: <phase>"`` when the planned minutes do not fit before the deadline.

    Args:
        now: the injected clock reading.
        deadline: :func:`night_deadline` of this night.
        phase: phase name (e.g. ``nightly-gate``).
        planned_minutes: the phase's estimate (``budget.py``).

    Returns:
        The ``infra_error`` text, or ``None`` when the phase may start.
    """
    if planned_minutes < 0:
        msg = "planned_minutes must be >= 0"
        raise ValueError(msg)
    if _aware(now) + timedelta(minutes=planned_minutes) > _aware(deadline):
        return f"window_exceeded: {phase}"
    return None


def block_of(counter: int) -> int:
    """Nightly block ``k = counter mod 3`` (D299).

    >>> block_of(4)
    1
    """
    if counter < 0:
        msg = "nightly counter must be >= 0"
        raise ValueError(msg)
    return counter % BLOCKS


def baseline_refs(counter: int) -> tuple[str, str]:
    """``(gate ref, drift ref)`` = ``(nightly-b<k>, release-b<k>)`` for the counter (N1.4, D305)."""
    k = block_of(counter)
    return f"nightly-b{k}", f"release-b{k}"


def updates_last_nightly_at(status: str) -> bool:
    """True for ``ok``/``failed`` only; skips and aborts keep ``last_nightly_at`` (A13-M3)."""
    return status in COMPLETED
