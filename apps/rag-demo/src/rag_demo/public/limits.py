"""In-process rate limits of the public demo (T8.4, ADR-0012, UI12-10, UI12-14).

Token buckets per client key, per-key and global daily counters and a concurrency cap, all in
memory of one process: a restart resets them (accepted; the e2e relies on it). The client key is
the IPv4 address or the IPv6 /64 prefix of ONE source: the ``X-Forwarded-For`` hop selected by
``TRUSTED_PROXY_HOPS`` (1 behind the tunnel, 0 = the TCP peer). ``CF-Connecting-IP`` is never read.
"""

import ipaddress
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rag_demo.public.errors import BUSY_RETRY_S, Rejection

Clock = Callable[[], float]
DAY_S = 86400


def client_key(peer: str | None, forwarded_for: str | None, hops: int) -> str:
    """The rate-limit key of one request.

    Args:
        peer: The TCP peer address.
        forwarded_for: The ``X-Forwarded-For`` header value.
        hops: ``TRUSTED_PROXY_HOPS``; the key is the hop that many places from the right of the
            header (the proxy appends the visitor address last), or the peer when ``hops`` is 0 or
            the header has fewer entries.

    Returns:
        The IPv4 address, or the IPv6 /64 prefix, as text; ``unknown`` when nothing parses.

    >>> client_key("10.0.0.1", "1.1.1.1, 2.2.2.2", 1)
    '2.2.2.2'
    >>> client_key("10.0.0.1", "9.9.9.9", 0)
    '10.0.0.1'
    >>> client_key("10.0.0.1", "2001:db8:1:2:aaaa::1", 1)
    '2001:db8:1:2::/64'
    """
    raw = peer
    if hops > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= hops:
            raw = parts[-hops]
    return _normalise(raw)


def _normalise(raw: str | None) -> str:
    try:
        addr = ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return "unknown"
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class Limiter:
    """Rate limits, daily caps and the concurrency cap of one process.

    Attributes:
        per_min: Requests per minute per client key.
        per_key_day: Requests per UTC day per client key.
        global_day: Requests per UTC day over all keys.
        max_concurrency: Generations running at once.
        clock: Epoch seconds (tests).
    """

    per_min: int = 10
    per_key_day: int = 100
    global_day: int = 2000
    max_concurrency: int = 2
    clock: Clock = time.time
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _buckets: dict[str, _Bucket] = field(default_factory=dict, repr=False)
    _day: int = field(default=-1, repr=False)
    _by_key: dict[str, int] = field(default_factory=dict, repr=False)
    _total: int = field(default=0, repr=False)
    _running: int = field(default=0, repr=False)

    def admit(self, key: str) -> Rejection | None:
        """Count one request of ``key``; ``None`` admits it, else the reason it is refused.

        A refused request does not use up a daily count.
        """
        now = self.clock()
        with self._lock:
            self._roll(now)
            if self._total >= self.global_day or self._by_key.get(key, 0) >= self.per_key_day:
                return Rejection("daily_limit", self._to_midnight(now))
            bucket = self._buckets.setdefault(key, _Bucket(float(self.per_min), now))
            rate = self.per_min / 60
            bucket.tokens = min(float(self.per_min), bucket.tokens + (now - bucket.updated) * rate)
            bucket.updated = now
            if bucket.tokens < 1:
                return Rejection("rate_limited", max(1, round((1 - bucket.tokens) / rate)))
            bucket.tokens -= 1
            self._by_key[key] = self._by_key.get(key, 0) + 1
            self._total += 1
            return None

    def acquire(self) -> Rejection | None:
        """Take a generation slot; ``busy`` (not queued) when all are taken."""
        with self._lock:
            if self._running >= self.max_concurrency:
                return Rejection("busy", BUSY_RETRY_S)
            self._running += 1
            return None

    def release(self) -> None:
        """Give a generation slot back."""
        with self._lock:
            self._running = max(0, self._running - 1)

    @property
    def running(self) -> int:
        """Generations in flight."""
        with self._lock:
            return self._running

    def reset(self) -> bool:
        """Empty buckets and counters; refused (``False``) while a generation is in flight."""
        with self._lock:
            if self._running > 0:
                return False
            self._buckets.clear()
            self._by_key.clear()
            self._total = 0
            return True

    def _roll(self, now: float) -> None:
        day = int(now // DAY_S)
        if day != self._day:
            self._day, self._by_key, self._total = day, {}, 0

    @staticmethod
    def _to_midnight(now: float) -> int:
        return max(1, int(DAY_S - now % DAY_S))
