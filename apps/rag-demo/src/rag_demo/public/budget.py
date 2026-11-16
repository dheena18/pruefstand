"""Daily token and request budget of the public demo: reserve first, settle afterwards (T8.4).

The worst case (``max_tokens``) is reserved before a generation starts and the real count is
settled afterwards, so concurrent requests cannot overshoot the cap. In-process, per UTC day.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rag_demo.public.errors import Rejection

DAY_S = 86400


@dataclass
class DailyBudget:
    """Tokens and requests per UTC day.

    Attributes:
        tokens: ``DEMO_DAILY_TOKENS``.
        requests: ``DEMO_DAILY_REQUESTS``.
        clock: Epoch seconds (tests).
    """

    tokens: int = 200_000
    requests: int = 2_000
    clock: Callable[[], float] = time.time
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _day: int = field(default=-1, repr=False)
    _used: int = field(default=0, repr=False)
    _count: int = field(default=0, repr=False)

    def reserve(self, worst_case: int) -> Rejection | None:
        """Reserve ``worst_case`` tokens and count one request, else ``budget_exhausted``."""
        now = self.clock()
        with self._lock:
            self._roll(now)
            if self._count >= self.requests or self._used + worst_case > self.tokens:
                return Rejection("budget_exhausted", max(1, int(DAY_S - now % DAY_S)))
            self._used += worst_case
            self._count += 1
            return None

    def settle(self, reserved: int, used: int) -> None:
        """Replace a reservation by the tokens really generated (never above the reservation)."""
        with self._lock:
            self._roll(self.clock())
            self._used = max(0, self._used - reserved + min(used, reserved))

    def reset(self) -> None:
        """Back to a full budget (test-only reset)."""
        with self._lock:
            self._used = self._count = 0

    def _roll(self, now: float) -> None:
        day = int(now // DAY_S)
        if day != self._day:
            self._day, self._used, self._count = day, 0, 0
