"""Heartbeat values: false_since, nightly status vocabulary (A12-M2, A13-M3); injected clock."""

from datetime import UTC, datetime

import pytest
from gate_orchestrator.heartbeat import check_nightly_status, nightly_fields, track_false_since

T10 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
T1015 = datetime(2026, 11, 10, 10, 15, tzinfo=UTC)
ALL_OK = {"tunnel_ok": True, "ollama_gpu0_ok": True, "ollama_gpu1_ok": True, "data_root_ok": True}


def test_false_since_keeps_the_first_false_time_and_clears_on_true() -> None:
    first = track_false_since({}, {**ALL_OK, "tunnel_ok": False}, T10)
    assert first["tunnel_ok_false_since"] == T10.isoformat()
    second = track_false_since(first, {**ALL_OK, "tunnel_ok": False}, T1015)
    assert second["tunnel_ok_false_since"] == T10.isoformat()
    third = track_false_since(second, ALL_OK, T1015)
    assert third == dict.fromkeys(
        [
            "tunnel_ok_false_since",
            "ollama_gpu0_ok_false_since",
            "ollama_gpu1_ok_false_since",
            "data_root_ok_false_since",
        ],
        "",
    )


def test_missing_field_or_naive_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="data_root_ok"):
        track_false_since(
            {}, {"tunnel_ok": True, "ollama_gpu0_ok": True, "ollama_gpu1_ok": True}, T10
        )
    with pytest.raises(ValueError, match="aware"):
        track_false_since({}, ALL_OK, datetime(2026, 11, 10))  # noqa: DTZ001 - naive input under test


@pytest.mark.parametrize("status", ["ok", "failed"])
def test_completed_nightly_sets_last_nightly_at(status: str) -> None:
    out = nightly_fields({"last_nightly_at": "2026-11-09T05:00:00+00:00"}, status, T10)
    assert out == {"last_nightly_status": status, "last_nightly_at": T10.isoformat()}


@pytest.mark.parametrize(
    "status",
    [
        "aborted: window_exceeded",
        "skipped: maintenance",
        "skipped: runner busy",
        "skipped: preflight data root unavailable",
    ],
)
def test_skip_or_abort_keeps_last_nightly_at(status: str) -> None:
    prev = {"last_nightly_at": "2026-11-09T05:00:00+00:00"}
    assert nightly_fields(prev, status, T10)["last_nightly_at"] == prev["last_nightly_at"]


@pytest.mark.parametrize("status", ["skipped: late start", "done", ""])
def test_unknown_nightly_status_is_refused(status: str) -> None:
    with pytest.raises(ValueError, match="last_nightly_status"):
        check_nightly_status(status)
