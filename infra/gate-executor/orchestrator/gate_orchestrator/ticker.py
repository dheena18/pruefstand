"""Heartbeat refresh while a job waits for the lock or runs (Y5.1, D225, D1031).

``ticking(tick)`` calls ``tick()`` at once and then every 15 minutes on a daemon thread until the
``with`` block ends, so ``executor-health.yml`` never sees a stale heartbeat during a 90-minute run
or a 2-hour lock wait. A failing tick (GitHub down, no token) is logged and retried at the next
interval; it never stops the job.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from pruefstand.core.errors import PruefstandError

INTERVAL_S = 15 * 60.0
LOG = logging.getLogger("gate_orchestrator.ticker")


@contextmanager
def ticking(tick: Callable[[], None], interval_s: float = INTERVAL_S) -> Iterator[None]:
    """Run ``tick`` now and every ``interval_s`` seconds while the block runs."""
    stop = threading.Event()

    def loop() -> None:
        while True:
            try:
                tick()
            except (PruefstandError, OSError) as exc:
                LOG.warning("heartbeat tick failed: %s", type(exc).__name__)
            if stop.wait(interval_s):
                return

    thread = threading.Thread(target=loop, name="heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=30)
