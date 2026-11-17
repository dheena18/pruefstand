"""Nightly scheduling helpers of the gate executor (T6.2b S4; D281, D298, D321, ADR-0019).

Pure functions of an injected clock and plain data (no I/O): the CLI subcommands that read the
state files and call them live in ``cmd_*`` modules. ``night-guard`` and ``backup-check`` are
elsewhere (``night_guard.py``, ``backup_check.py``); the window rules are in ``window.py``.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from gate_orchestrator.window import BERLIN, BLOCKS

SUNDAY = 6
RELEASE_REFS = tuple(f"release-b{k}" for k in range(BLOCKS))
FailKind = Literal["none", "hard", "statistical"]


def release_run_due(promoted_refs: Collection[str]) -> bool:
    """True while any of ``release-b0..b2`` is missing for the current fingerprint (D321).

    >>> release_run_due({"release-b0", "release-b1"})
    True
    >>> release_run_due({"release-b0", "release-b1", "release-b2", "main"})
    False
    """
    return not set(RELEASE_REFS) <= set(promoted_refs)


def cause_switches_due(started: datetime, *, forced: bool = False) -> bool:
    """True when the night starts on a Sunday (Europe/Berlin), or when forced (D223).

    Raises:
        ValueError: ``started`` is naive.
    """
    if started.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    return forced or started.astimezone(BERLIN).weekday() == SUNDAY


@dataclass(frozen=True)
class NightResult:
    """One completed night of ``state/nightly_fails.json``.

    Attributes:
        night: The Berlin date of the night's start.
        kind: ``hard`` (hard or absolute fail), ``statistical`` or ``none``.
    """

    night: date
    kind: FailKind


def nightly_alarm(history: Sequence[NightResult]) -> bool:
    """Whether the issue ``nightly-failed`` opens now (D281, AI12-12).

    At once on a hard or absolute fail; on a statistical fail only when the night before (the
    previous completed night in ``history``, oldest first) failed too, so one noisy night does
    not alarm.

    >>> from datetime import date
    >>> n = lambda d, k: NightResult(date(2026, 11, d), k)
    >>> nightly_alarm([n(1, "none"), n(2, "statistical")])
    False
    >>> nightly_alarm([n(1, "statistical"), n(2, "statistical")])
    True
    >>> nightly_alarm([n(1, "none"), n(2, "hard")])
    True
    """
    if not history:
        return False
    last = history[-1].kind
    if last == "hard":
        return True
    return last == "statistical" and len(history) > 1 and history[-2].kind != "none"


@dataclass(frozen=True)
class JudgeChoice:
    """The nightly judge and whether it is a fallback.

    Attributes:
        judge_id: The catalogue id used.
        judge_fallback: True when the configured judge is not in the catalogue.
    """

    judge_id: str
    judge_fallback: bool


def nightly_judge(catalogue: Mapping[str, Mapping[str, str]], configured: str) -> JudgeChoice:
    """The judge of the nightly: the catalogue's ``judge`` entry on ``gpu1`` (ADR-0019, D329).

    Args:
        catalogue: model id -> entry with ``role`` and ``server`` (``infra/gpu/models.yaml``).
        configured: ``judge.nightly`` of the config.

    Returns:
        The configured judge when it is in the catalogue, else the catalogue's own judge with
        ``judge_fallback=True``.

    Raises:
        LookupError: The catalogue has no judge on ``gpu1``.
    """
    judges = sorted(
        i for i, e in catalogue.items() if e.get("role") == "judge" and e.get("server") == "gpu1"
    )
    if not judges:
        msg = "the catalogue has no judge on gpu1"
        raise LookupError(msg)
    if configured in judges:
        return JudgeChoice(configured, judge_fallback=False)
    return JudgeChoice(judges[0], judge_fallback=True)


def prune_due(now: datetime, last_pruned: tuple[int, int] | None) -> bool:
    """True on the first poll of a new UTC month (``last_pruned`` = ``(year, month)`` or None).

    The monthly ``baseline prune`` (D110) runs once per month; a poll that misses day 1 still
    prunes on the next one.

    >>> from datetime import datetime, timezone
    >>> prune_due(datetime(2026, 12, 1, 0, 3, tzinfo=timezone.utc), (2026, 11))
    True
    >>> prune_due(datetime(2026, 12, 9, 8, 0, tzinfo=timezone.utc), (2026, 12))
    False
    """
    if now.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    utc = now.utctimetuple()
    return last_pruned is None or (utc.tm_year, utc.tm_mon) > last_pruned


@dataclass(frozen=True)
class RunInfo:
    """What the promotion selection needs of one run directory.

    Attributes:
        run_id: The run id (sorts by creation time).
        kind: ``nightly`` (one block) or ``release`` (all of ``full``).
        block: The nightly block ``k`` (None for a release run).
        complete: ``run.json`` ``complete``.
        promoted: Already promoted to its refs.
        judge_fallback, judge_drift, judge_degraded: The run's judge flags.
        judge_truncated: A judged metric is informational for ``judge_truncated``.
        infra_error: ``run.json`` ``infra_error`` (any text).
    """

    run_id: str
    kind: Literal["nightly", "release"]
    block: int | None
    complete: bool
    promoted: bool = False
    judge_fallback: bool = False
    judge_drift: bool = False
    judge_degraded: bool = False
    judge_truncated: bool = False
    infra_error: str | None = None


def promotable(run: RunInfo) -> bool:
    """A run may be promoted only when complete, not yet promoted and not flagged (D321, Y4.4)."""
    flagged = (
        run.judge_fallback
        or run.judge_drift
        or run.judge_degraded
        or run.judge_truncated
        or run.infra_error is not None
    )
    return run.complete and not run.promoted and not flagged


def promotable_nightly(runs: Sequence[RunInfo]) -> RunInfo | None:
    """The newest promotable run (by ``run_id``), or None."""
    eligible = [r for r in runs if promotable(r)]
    return max(eligible, key=lambda r: r.run_id, default=None)


def promotion_refs(run: RunInfo) -> tuple[str, ...]:
    """The refs a run is promoted to: ``nightly-b<k>``, or ``release-b0..b2`` for a release run."""
    if run.kind == "release":
        return RELEASE_REFS
    if run.block is None or not 0 <= run.block < BLOCKS:
        msg = f"a nightly run needs a block 0..{BLOCKS - 1}"
        raise ValueError(msg)
    return (f"nightly-b{run.block}",)
