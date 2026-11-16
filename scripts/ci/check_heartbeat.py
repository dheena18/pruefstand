"""Executor heartbeat check for ``executor-health.yml`` (T6.2b S8, A13-M3..M5, D1092).

A pure function of ``now``, the ``heartbeat.json`` content (branch ``heartbeat`` of
``dheena18/pruefstand-dashboard-data``) and the labels of the open issues; it returns the issue
actions the workflow applies with ``gh``. Stateless: the payload carries ``*_false_since`` times.

Usage: ``check_heartbeat.py --heartbeat <file|-> --now <iso> [--open <label>]... [--marker <m>]...``
(one line) prints the actions as JSON (``[]`` when nothing is to do).
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

STALE = timedelta(hours=2)
NO_NIGHTLY = timedelta(hours=26)
BACKUP_DAYS = 8
HEALTH_FIELDS = ("tunnel_ok", "ollama_gpu0_ok", "ollama_gpu1_ok", "data_root_ok")
TITLES = {
    "executor-down": "executor down",
    "backup-stale": "laptop backup stale",
    "nightly-failed": "nightly failed",
    "nightly-skipped": "nightly skipped",
}
Heartbeat = Mapping[str, object]


@dataclass(frozen=True)
class Action:
    """An issue action: ``op`` is ``open``, ``comment`` or ``close``; ``marker`` dedupes."""

    label: str
    op: str
    title: str
    body: str
    marker: str = ""


def parse(text: str) -> dict[str, object] | None:
    """The heartbeat object, or ``None`` when the text is not a JSON object."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min"


def _down_reasons(hb: Heartbeat | None, now: datetime) -> list[str]:
    ts = _time(hb.get("ts")) if hb is not None else None
    if ts is None:
        return ["heartbeat.json is missing or has no valid ts"]
    reasons = [f"heartbeat is {_age(now - ts)} old"] if now - ts > STALE else []
    if hb is not None and hb.get("maintenance") is not True:  # A13-M4: field alerts paused
        for field in HEALTH_FIELDS:
            since = _time(hb.get(f"{field}_false_since"))
            if since is not None and now - since > STALE:
                reasons.append(f"{field} false for {_age(now - since)}")
    return reasons


def _nightly_skipped(hb: Heartbeat, now: datetime) -> str:
    status = str(hb.get("last_nightly_status", ""))
    if status.startswith(("skipped: ", "aborted: ")):
        return f"last_nightly_status: {status}"
    last = _time(hb.get("last_nightly_at"))
    if last is None or now - last > NO_NIGHTLY:
        return "no completed nightly for more than 26 h"
    return ""


def _conditions(hb: Heartbeat | None, now: datetime) -> dict[str, str]:
    """Label -> reason text when its alert holds; a label that is absent is healthy."""
    out: dict[str, str] = {}
    down = _down_reasons(hb, now)
    if down:
        out["executor-down"] = "; ".join(down)
    if hb is None or _time(hb.get("ts")) is None:
        return out  # an unusable heartbeat says nothing about the other alerts
    age = hb.get("laptop_backup_age_days")
    if isinstance(age, int | float) and age > BACKUP_DAYS:
        out["backup-stale"] = f"laptop_backup_age_days = {age} (> {BACKUP_DAYS})"
    if hb.get("last_nightly_result") == "failure":
        out["nightly-failed"] = "last_nightly_result = failure"
    skipped = _nightly_skipped(hb, now)
    if skipped:
        out["nightly-skipped"] = skipped
    return out


def evaluate(
    hb: Heartbeat | None,
    now: datetime,
    *,
    open_labels: set[str],
    markers: frozenset[str] | set[str] = frozenset(),
) -> list[Action]:
    """The issue actions for one hourly run (see the module docstring)."""
    conditions = _conditions(hb, now)
    actions: list[Action] = []
    for label, title in TITLES.items():
        reason = conditions.get(label)
        if reason:
            op = "comment" if label in open_labels else "open"
            actions.append(Action(label, op, title, reason))
        elif label in open_labels and _may_close(label, hb):
            actions.append(Action(label, "close", title, "healthy again"))
    if hb is not None and hb.get("drift_no_release_baseline") is True:
        marker = f"drift-no-release:{hb.get('release_tag', 'unknown')}"
        if marker not in markers:
            op = (
                "comment"
                if "nightly-skipped" in open_labels or "nightly-skipped" in conditions
                else "open"
            )
            body = f"drift: no release baseline for {hb.get('release_tag', 'unknown')} ({marker})"
            actions.append(Action("nightly-skipped", op, TITLES["nightly-skipped"], body, marker))
    return actions


def _may_close(label: str, hb: Heartbeat | None) -> bool:
    if label == "nightly-skipped":  # closed only by the next completed nightly (N4.3)
        return hb is not None and hb.get("last_nightly_status") == "ok"
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: print the actions as JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--heartbeat", required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--open", action="append", default=[])
    ap.add_argument("--marker", action="append", default=[])
    args = ap.parse_args(argv)
    text = sys.stdin.read() if args.heartbeat == "-" else Path(args.heartbeat).read_text("utf-8")
    now = datetime.fromisoformat(args.now)
    actions = evaluate(parse(text), now, open_labels=set(args.open), markers=set(args.marker))
    print(json.dumps([asdict(a) for a in actions]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
