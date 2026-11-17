"""T8.4: in-process rate limits, client key and concurrency cap."""

import inspect

from rag_demo.public import limits
from rag_demo.public.limits import Limiter, client_key


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_state_is_in_process_only() -> None:
    first = Limiter(per_min=1, clock=Clock())
    assert first.admit("a") is None
    assert first.admit("a") is not None
    assert Limiter(per_min=1, clock=Clock()).admit("a") is None  # a new process starts empty
    source = inspect.getsource(limits)
    assert "sqlite" not in source
    assert "open(" not in source  # no file is read or written


def test_the_eleventh_request_in_a_minute_is_rate_limited() -> None:
    clock = Clock()
    limiter = Limiter(per_min=10, clock=clock)
    assert all(limiter.admit("1.2.3.4") is None for _ in range(10))
    refused = limiter.admit("1.2.3.4")
    assert refused is not None
    assert (refused.code, refused.status) == ("rate_limited", 429)
    assert refused.retry_after_s is not None
    assert refused.retry_after_s > 0
    assert limiter.admit("5.6.7.8") is None  # another key is unaffected
    clock.now += 7  # 10 per minute refills one token in 6 s
    assert limiter.admit("1.2.3.4") is None


def test_the_per_key_daily_cap_is_a_daily_limit() -> None:
    limiter = Limiter(per_min=100, per_key_day=2, clock=Clock())
    assert limiter.admit("k") is None
    assert limiter.admit("k") is None
    refused = limiter.admit("k")
    assert refused is not None
    assert refused.code == "daily_limit"
    assert limiter.admit("other") is None


def test_a_refused_request_does_not_use_up_a_daily_count() -> None:
    limiter = Limiter(per_min=1, per_key_day=2, clock=Clock())
    assert limiter.admit("k") is None
    for _ in range(5):
        assert limiter.admit("k") is not None  # rate limited
    limiter.clock = Clock(1_000_000.0 + 120)
    assert limiter.admit("k") is None  # the second of two daily requests, not the sixth


def test_the_global_cap_refuses_every_key_and_a_new_day_admits_again() -> None:
    clock = Clock(86400 * 20 + 100.0)
    limiter = Limiter(per_min=100, global_day=2, clock=clock)
    assert limiter.admit("a") is None
    assert limiter.admit("b") is None
    refused = limiter.admit("c")
    assert refused is not None
    assert refused.code == "daily_limit"
    assert refused.retry_after_s == 86400 - 100
    clock.now += 86400
    assert limiter.admit("c") is None


def test_the_concurrency_cap_is_busy_with_a_five_second_retry() -> None:
    limiter = Limiter(max_concurrency=2)
    assert limiter.acquire() is None
    assert limiter.acquire() is None
    busy = limiter.acquire()
    assert busy is not None
    assert (busy.code, busy.status, busy.retry_after_s) == ("busy", 429, 5)
    limiter.release()
    assert limiter.acquire() is None


def test_reset_clears_the_limits_but_not_while_a_generation_runs() -> None:
    limiter = Limiter(per_min=1, clock=Clock())
    assert limiter.admit("k") is None
    assert limiter.admit("k") is not None
    assert limiter.acquire() is None
    assert limiter.reset() is False  # 409 territory: nothing changes
    assert limiter.admit("k") is not None
    limiter.release()
    assert limiter.reset() is True
    assert limiter.admit("k") is None


def test_key_from_the_trusted_forwarded_hop() -> None:
    header = "6.6.6.6, 1.1.1.1, 2.2.2.2"  # a client-forged first hop, then the proxies' view
    assert client_key("10.0.0.1", header, 1) == "2.2.2.2"
    assert client_key("10.0.0.1", header, 2) == "1.1.1.1"
    assert client_key("10.0.0.1", "9.9.9.9", 2) == "10.0.0.1"  # fewer hops than trusted: the peer


def test_zero_hops_use_the_peer_and_ignore_the_header() -> None:
    assert client_key("172.18.0.1", "1.1.1.1", 0) == "172.18.0.1"


def test_ipv6_addresses_of_one_64_prefix_share_a_key() -> None:
    a = client_key(None, "2001:db8:aa:bb:1::1", 1)
    b = client_key(None, "2001:db8:aa:bb:ffff::9", 1)
    c = client_key(None, "2001:db8:aa:cc::1", 1)
    assert a == b == "2001:db8:aa:bb::/64"
    assert c != a


def test_an_unparsable_address_shares_one_unknown_key() -> None:
    assert client_key("garbage", None, 0) == "unknown"
    assert client_key(None, None, 1) == "unknown"


def test_a_hop_with_a_port_or_brackets_is_parsed_not_collapsed_to_unknown() -> None:
    assert client_key(None, "1.2.3.4:5555", 1) == "1.2.3.4"
    assert client_key(None, "[2001:db8:aa:bb::1]:443", 1) == "2001:db8:aa:bb::/64"
    assert client_key(None, "[2001:db8:aa:bb::1]", 1) == "2001:db8:aa:bb::/64"
    assert client_key(None, "::ffff:1.2.3.4", 1) == "1.2.3.4"  # an IPv4-mapped address
