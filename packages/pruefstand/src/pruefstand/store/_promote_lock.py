"""Serialised promotions of one data root (Opus review of D1120: check-then-act race).

``promote_lock`` takes an exclusive ``flock`` on ``<root>/.promote.lock`` for one promotion, and
``check_expected`` refuses the promotion when the baseline stored for (fingerprint, ref) is no
longer the one the run was gated against (another promote won the race). The lock file is no
safe fingerprint name, so readers and ``prune`` skip it.
"""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pruefstand.core.models.baseline import ExpectedBaseline
from pruefstand.store.promote import BaselineRefused

LOCK_NAME = ".promote.lock"


@contextmanager
def promote_lock(root: Path) -> Iterator[None]:
    """Hold the data root's promotion lock (blocks until it is free)."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / LOCK_NAME).open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def check_expected(current: str | None, expected: ExpectedBaseline | None, where: str) -> None:
    """Refuse when the stored baseline changed since the gate decided.

    Raises:
        BaselineRefused: ``expected`` is given and differs from ``current`` (exit 1).
    """
    if expected is None or expected.run_id == current:
        return
    now = current or "none"
    msg = (
        f"the baseline of {where} changed during the promote (gated against"
        f" {expected.run_id or 'none'}, stored now {now});"
        " run `pruefstand gate` again; not promoted"
    )
    raise BaselineRefused(msg)
