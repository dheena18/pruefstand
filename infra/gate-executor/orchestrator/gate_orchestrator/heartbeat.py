"""Heartbeat payload values (Y5.1, D225, N4.3, A12-M2, A13-M3, A13-M4); pure, clock injected.

``*_false_since`` keeps the ISO time a health field first turned ``false`` (empty while ``true``);
the previous values live in ``$PRUEFSTAND_HOME/state/health_since.json``. ``last_nightly_at``
changes only for ``ok``/``failed``; a skip or abort only sets ``last_nightly_status``.
``maintenance`` is the presence of ``/var/lib/pruefstand/MAINTENANCE``. Pushing
(``push_heartbeat``, T6.1) and the 15-min thread are the caller's.
"""

from collections.abc import Mapping
from datetime import datetime

from gate_orchestrator.window import updates_last_nightly_at

HEALTH_FIELDS = ("tunnel_ok", "ollama_gpu0_ok", "ollama_gpu1_ok", "data_root_ok")
NIGHTLY_STATUSES = frozenset(
    {"ok", "failed", "aborted: window_exceeded", "skipped: maintenance", "skipped: runner busy"}
)


def track_false_since(
    previous: Mapping[str, str], health: Mapping[str, bool], now: datetime
) -> dict[str, str]:
    """``{<field>_false_since: iso | ""}`` for the four health fields.

    Raises:
        ValueError: a health field is missing or ``now`` is naive.
    """
    if now.tzinfo is None:
        msg = "now must be timezone-aware"
        raise ValueError(msg)
    out: dict[str, str] = {}
    for name in HEALTH_FIELDS:
        if name not in health:
            msg = f"health field {name} missing"
            raise ValueError(msg)
        key = f"{name}_false_since"
        out[key] = "" if health[name] else (previous.get(key) or now.isoformat())
    return out


def check_nightly_status(status: str) -> str:
    """Return ``status`` if it is in the A13-M3 vocabulary (incl. ``skipped: preflight <reason>``).

    Raises:
        ValueError: any other value.
    """
    if status in NIGHTLY_STATUSES or status.startswith("skipped: preflight "):
        return status
    msg = f"not a last_nightly_status value: {status!r}"
    raise ValueError(msg)


def nightly_fields(previous: Mapping[str, str], status: str, now: datetime) -> dict[str, str]:
    """``last_nightly_status`` and ``last_nightly_at`` after a nightly ended with ``status``."""
    at = now.isoformat() if updates_last_nightly_at(status) else previous.get("last_nightly_at", "")
    return {"last_nightly_status": check_nightly_status(status), "last_nightly_at": at}
