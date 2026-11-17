"""``gate-orchestrator backup-check`` (D1095): laptop backup age into summary and heartbeat."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from gate_orchestrator import heartbeat_store
from gate_orchestrator.backup_check import laptop_backup_age_days, summary


def backup_check(args: argparse.Namespace) -> int:
    """Exit 0 after writing the summary and pushing the heartbeat; 1 without a data root."""
    root = os.environ.get("PRUEFSTAND_DATA_ROOT", "")
    if not root or not Path(root).is_dir():
        sys.stderr.write("backup-check: PRUEFSTAND_DATA_ROOT is not a directory\n")
        return 1
    now = datetime.now(UTC)
    age, reason = laptop_backup_age_days(Path(root) / "backups", now)
    text = summary(age, reason)
    if args.summary:
        with Path(args.summary).open("a", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)
    path = heartbeat_store.payload_path(os.environ)
    heartbeat_store.update(path, {"laptop_backup_age_days": f"{age:g}"}, now)
    return 0
