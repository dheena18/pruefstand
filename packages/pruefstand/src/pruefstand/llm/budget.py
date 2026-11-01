"""Run budget: USD, tokens and a request cap with atomic reservations (R9 X4.5, D9-06)."""

import asyncio

from pruefstand.core.errors import BudgetExceeded
from pruefstand.core.models.llm import LLMResponse


class Budget:
    """Cumulative limits for one run.

    The budget assumes a **single event loop**: ``reserve`` / ``release`` serialise on an
    ``asyncio.Lock``, ``charge`` is synchronous and therefore atomic within that loop.

    Args:
        max_usd: Cost limit in USD; None = unlimited.
        max_tokens: Limit on prompt plus completion tokens; None = unlimited.
        max_requests: Cap on charged plus reserved requests; None = unlimited.

    Examples:
        >>> b = Budget(max_usd=None, max_tokens=None, max_requests=2)
        >>> b.requests_remaining
        2
    """

    def __init__(
        self, max_usd: float | None, max_tokens: int | None, max_requests: int | None = None
    ) -> None:
        self._max_usd = max_usd
        self._max_tokens = max_tokens
        self._max_requests = max_requests
        self._usd = 0.0
        self._tokens = 0
        self._charged = 0
        self._reserved = 0
        self._lock = asyncio.Lock()

    @property
    def requests_remaining(self) -> int | None:
        """Return ``max_requests - charged - reserved`` (None without a cap); information only."""
        if self._max_requests is None:
            return None
        return self._max_requests - self._charged - self._reserved

    async def reserve(self, n: int) -> bool:
        """Reserve ``n`` requests atomically.

        Args:
            n: Number of requests to hold.

        Returns:
            True when reserved (always, without a request cap); False when the cap would be
            passed, in which case nothing is reserved.
        """
        async with self._lock:
            if self._max_requests is not None and (
                self._charged + self._reserved + n > self._max_requests
            ):
                return False
            self._reserved += n
            return True

    async def release(self, n: int) -> None:
        """Return ``n`` unused reserved requests.

        Raises:
            ValueError: ``n`` is larger than the currently reserved number.
        """
        async with self._lock:
            if n > self._reserved:
                msg = f"cannot release {n} requests, only {self._reserved} are reserved"
                raise ValueError(msg)
            self._reserved -= n

    def charge(self, r: LLMResponse) -> None:
        """Add one answered request.

        A charge while a reservation is held consumes one reserved slot and never raises for the
        request cap; an unreserved charge beyond ``max_requests`` does.

        Args:
            r: The response whose cost and tokens are added.

        Raises:
            BudgetExceeded: USD, tokens or (unreserved) requests are over their limit after adding.
        """
        self._usd += r.cost_usd
        self._tokens += r.usage.prompt_tokens + r.usage.completion_tokens
        reserved = self._reserved > 0
        if reserved:
            self._reserved -= 1
        self._charged += 1
        if self._max_usd is not None and self._usd > self._max_usd:
            msg = f"USD budget exceeded: {self._usd:.4f} > {self._max_usd}"
            raise BudgetExceeded(msg)
        if self._max_tokens is not None and self._tokens > self._max_tokens:
            msg = f"token budget exceeded: {self._tokens} > {self._max_tokens}"
            raise BudgetExceeded(msg)
        over = (
            self._max_requests is not None and self._charged + self._reserved > self._max_requests
        )
        if over and not reserved:
            msg = f"request budget exceeded: cap {self._max_requests}"
            raise BudgetExceeded(msg)
