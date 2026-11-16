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


@dataclass(frozen=True)
class Reservation:
    """A reservation of one request: the UTC day it was made on and the tokens held.

    Attributes:
        day: UTC day number of the reservation; a settle on another day does nothing.
        tokens: The worst case reserved.
    """

    day: int
    tokens: int


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

    def reserve(self, worst_case: int) -> Reservation | Rejection:
        """Reserve ``worst_case`` tokens and count one request, else ``budget_exhausted``.

        Returns:
            The ``Reservation`` to settle later, or the ``Rejection``.
        """
        now = self.clock()
        with self._lock:
            self._roll(now)
            if self._count >= self.requests or self._used + worst_case > self.tokens:
                return Rejection("budget_exhausted", max(1, int(DAY_S - now % DAY_S)))
            self._used += worst_case
            self._count += 1
            return Reservation(self._day, worst_case)

    def settle(self, reservation: Reservation, used: int) -> None:
        """Replace a reservation by the tokens really generated (never above the reservation).

        A reservation of an earlier UTC day is ignored: that day's counters are gone, and
        subtracting from today's would erase reservations that are still running (Opus B1).
        """
        with self._lock:
            self._roll(self.clock())
            if reservation.day != self._day:
                return
            kept = min(used, reservation.tokens)
            self._used = max(0, self._used - reservation.tokens + kept)

    def reset(self) -> None:
        """Back to a full budget (test-only reset)."""
        with self._lock:
            self._used = self._count = 0

    def _roll(self, now: float) -> None:
        day = int(now // DAY_S)
        if day != self._day:
            self._day, self._used, self._count = day, 0, 0
