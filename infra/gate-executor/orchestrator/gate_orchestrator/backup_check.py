"""``backup-check`` (Y5.5, D229, A13-M10, D1095): age of the owner's laptop copy of the backup.

The owner writes ``$PRUEFSTAND_DATA_ROOT/backups/laptop-receipt.json`` (``{bundle, sha256,
copied_at}``) after copying the newest bundle to the laptop. The receipt counts only when its
``sha256`` equals the sha256 of a bundle still kept under ``backups/<date>/``; a missing, malformed
or unmatched receipt is stale (:data:`STALE_DAYS`). Above :data:`WARN_DAYS` the job summary warns
and ``executor-health.yml`` opens ``backup-stale`` from the heartbeat value.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

BUNDLE = "pruefstand-gate.bundle.tar.age"
RECEIPT = "laptop-receipt.json"
WARN_DAYS = 8
STALE_DAYS = 999
_SHA = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def laptop_backup_age_days(backups: Path, now: datetime) -> tuple[float, str]:
    """``(age in days, reason)`` of the laptop copy; :data:`STALE_DAYS` when it does not count.

    Args:
        backups: ``$PRUEFSTAND_DATA_ROOT/backups``.
        now: aware clock reading.

    Returns:
        The age (rounded to 0.1 day) and a one-line reason for the job summary.
    """
    try:
        receipt = json.loads((backups / RECEIPT).read_text(encoding="utf-8"))
        sha = str(receipt["sha256"]).lower()
        copied = datetime.fromisoformat(str(receipt["copied_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return STALE_DAYS, "no valid laptop-receipt.json"
    if copied.tzinfo is None or _SHA.fullmatch(sha) is None:
        return STALE_DAYS, "laptop-receipt.json needs an aware copied_at and a sha256"
    kept = sorted(backups.glob(f"*/{BUNDLE}"))
    if not any(_sha256(bundle) == sha for bundle in kept):
        return STALE_DAYS, "the receipt's sha256 matches no kept bundle"
    age = max(0.0, (now - copied).total_seconds() / 86400)
    return round(age, 1), f"laptop copy is {age:.1f} days old"


def summary(age: float, reason: str) -> str:
    """Markdown for ``$GITHUB_STEP_SUMMARY``; warns above :data:`WARN_DAYS`."""
    head = "WARNING: laptop backup stale" if age > WARN_DAYS else "laptop backup ok"
    return f"### backup-check\n\n{head}: {reason} (laptop_backup_age_days = {age:g})\n"
