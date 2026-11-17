"""The executor's last heartbeat payload and its publication (Y5.1, D225, D1095).

Every writer (a job's 15-min thread, ``backup-check``) updates a few keys of the last payload
kept in ``$PRUEFSTAND_HOME/state/heartbeat.json`` and pushes the whole payload with
``push_heartbeat`` (T6.1: string values only, branch ``heartbeat`` of the dashboard-data repo),
so no writer drops the keys of another. ``ts`` is refreshed on every write.
"""

import json
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from pruefstand.store.dashboard_repo import push_heartbeat

DASHBOARD_REPO = "dheena18/pruefstand-dashboard-data"
Pusher = Callable[[str, Mapping[str, str]], str]


def payload_path(env: Mapping[str, str]) -> Path:
    """``$PRUEFSTAND_HOME/state/heartbeat.json``.

    Raises:
        KeyError: ``PRUEFSTAND_HOME`` is unset.
    """
    return Path(env["PRUEFSTAND_HOME"]) / "state" / "heartbeat.json"


def load(path: Path) -> dict[str, str]:
    """The last payload; ``{}`` when missing or not a JSON object of strings."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


def update(
    path: Path, changes: Mapping[str, str], now: datetime, push: Pusher | None = None
) -> dict[str, str]:
    """Merge ``changes`` and a fresh ``ts`` into the stored payload, save it, push it.

    Args:
        path: :func:`payload_path`.
        changes: keys to set (string values).
        now: aware clock reading.
        push: ``(repo, payload) -> sha``; default :func:`push_heartbeat` (``DASHBOARD_DATA_PAT``).

    Returns:
        The payload that was pushed.
    """
    payload = {**load(path), **changes, "ts": now.isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
    Path(tmp.name).replace(path)
    (push or push_heartbeat)(DASHBOARD_REPO, payload)
    return payload
