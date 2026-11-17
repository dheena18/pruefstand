"""Executor heartbeat check for ``executor-health.yml`` (T6.2b S8, A13-M3..M5, D1092).

A pure function of ``now``, the ``heartbeat.json`` content (branch ``heartbeat`` of
``dheena18/pruefstand-dashboard-data``) and the labels of the open issues; it returns the issue
actions the workflow applies with ``gh``. Stateless: the payload carries ``*_false_since`` times.

Usage: ``check_heartbeat.py --heartbeat <file|-> --now <iso> [--open <label>]... [--marker <m>]...``
(one line) prints the actions as JSON (``[]`` when nothing is to do).
"""

import argparse
import json
import re
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
# Heartbeat text reaches public issues: release tags must match this (the workflow's marker grep
# uses the same class), anything else becomes INVALID_TAG; status text keeps only _TEXT_OK chars.
TAG = re.compile(r"[A-Za-z0-9._-]{1,64}")
INVALID_TAG = "invalid-tag"
_TEXT_DROP = re.compile(r"[^A-Za-z0-9 ._:-]")


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


def _flag(value: object) -> bool | None:
    """A payload flag: push_heartbeat writes ``"true"``/``"false"`` strings (bools accepted)."""
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False}.get(value) if isinstance(value, str) else None


def _number(value: object) -> float | None:
    """A numeric payload value (``"9"``, ``"8.5"`` or a number); anything else is ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _tag(value: object) -> str:
    return value if isinstance(value, str) and TAG.fullmatch(value) else INVALID_TAG


def _text(value: object) -> str:
    """Heartbeat text as inline code: no mentions, links or markup (review #198)."""
    clean = _TEXT_DROP.sub("", str(value)).replace("https:", "https").replace("http:", "http")
    return f"`{clean[:80]}`"


def _age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min"


def _down_reasons(hb: Heartbeat | None, now: datetime) -> list[str]:
    ts = _time(hb.get("ts")) if hb is not None else None
    if ts is None:
        return ["heartbeat.json is missing or has no valid ts"]
    reasons = [f"heartbeat is {_age(now - ts)} old"] if now - ts > STALE else []
    if hb is not None and _flag(hb.get("maintenance")) is not True:  # A13-M4: field alerts paused
        for field in HEALTH_FIELDS:
            since = _time(hb.get(f"{field}_false_since"))
            if since is not None and now - since > STALE:
                reasons.append(f"{field} false for {_age(now - since)}")
    return reasons


def _nightly_skipped(hb: Heartbeat, now: datetime) -> str:
    status = str(hb.get("last_nightly_status", ""))
    if status.startswith(("skipped: ", "aborted: ")):
        return f"last_nightly_status: {_text(status)}"
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
    age = _number(hb.get("laptop_backup_age_days"))
    if age is not None and age > BACKUP_DAYS:
        out["backup-stale"] = f"laptop_backup_age_days = {age:g} (> {BACKUP_DAYS})"
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
    # review #198: an unknown, empty or stale heartbeat (or a failing health field) is no evidence
    # that anything recovered, so nothing is closed while executor-down holds.
    # review #198 minor 1: a partial heartbeat (health field missing or not a bool) is unknown.
    may_close = "executor-down" not in conditions and _complete(hb)
    actions: list[Action] = []
    closed: set[str] = set()
    for label, title in TITLES.items():
        reason = conditions.get(label)
        if reason:
            op = "comment" if label in open_labels else "open"
            actions.append(Action(label, op, title, reason))
        elif may_close and label in open_labels and _may_close(label, hb):
            actions.append(Action(label, "close", title, "healthy again"))
            closed.add(label)
    if hb is not None and _flag(hb.get("drift_no_release_baseline")) is True:
        tag = _tag(hb.get("release_tag"))
        marker = f"drift-no-release:{tag}"
        if marker not in markers:
            # minor 2: never a comment on an issue this run closes (the note would be lost)
            still_open = "nightly-skipped" in open_labels and "nightly-skipped" not in closed
            op = "comment" if still_open or "nightly-skipped" in conditions else "open"
            body = f"drift: no release baseline for `{tag}` (`{marker}`)"
            actions.append(Action("nightly-skipped", op, TITLES["nightly-skipped"], body, marker))
    return actions


def _complete(hb: Heartbeat | None) -> bool:
    return hb is not None and all(_flag(hb.get(f)) is not None for f in HEALTH_FIELDS)


def _may_close(label: str, hb: Heartbeat | None) -> bool:
    """Close only on positive evidence in the label's own field (missing = unknown)."""
    if hb is None:
        return False
    if label == "nightly-skipped":  # closed only by the next completed nightly (N4.3)
        return hb.get("last_nightly_status") == "ok"
    if label == "backup-stale":
        return _number(hb.get("laptop_backup_age_days")) is not None
    if label == "nightly-failed":
        result = hb.get("last_nightly_result")
        return isinstance(result, str) and bool(result)
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
