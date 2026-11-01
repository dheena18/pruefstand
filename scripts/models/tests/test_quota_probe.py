"""Tests for the GitHub Models quota probe (T0.6 S6/S7): parsing, tables, summary, budget.

Pure functions on header dicts and records; the one real request is a `network` test that needs
a token.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from models.quota_probe import (
    Record,
    budget_check,
    load_records,
    make_sender,
    parse_rate_error,
    parse_rate_headers,
    render_burst_table,
    render_summary,
    run_burst,
    summarise_daily,
)


def _rec(
    model: str,
    index: int,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    ts: str = "2026-11-01T00:00:00+00:00",
    error: str | None = None,
) -> Record:
    return Record(
        ts=ts,
        model=model,
        index=index,
        status=status,
        headers=headers or {},
        retry_after=None,
        error=error,
    )


def test_remaining_requests_header_is_parsed_to_int() -> None:
    windows = parse_rate_headers({"X-RateLimit-Remaining-Requests": "149"})
    assert windows["requests"].remaining == 149
    assert windows["requests"].limit is None


def test_day_and_minute_windows_are_parsed_separately() -> None:
    windows = parse_rate_headers(
        {
            "x-ratelimit-limit-requests-day": "150",
            "x-ratelimit-remaining-requests-day": "140",
            "x-ratelimit-limit-requests-minute": "15",
            "x-ratelimit-remaining-requests-minute": "3",
            "x-ratelimit-reset-requests-minute": "42s",
            "content-type": "application/json",
        }
    )
    assert set(windows) == {"requests-day", "requests-minute"}
    assert (windows["requests-day"].limit, windows["requests-day"].remaining) == (150, 140)
    assert (windows["requests-minute"].limit, windows["requests-minute"].remaining) == (15, 3)
    assert windows["requests-minute"].reset == "42s"


def test_token_headers_are_a_separate_resource() -> None:
    windows = parse_rate_headers({"x-ratelimit-remaining-tokens": "9000"})
    assert windows["tokens"].remaining == 9000
    assert "requests" not in windows


def test_unparsable_values_become_none() -> None:
    assert parse_rate_headers({"x-ratelimit-limit-requests": "lots"})["requests"].limit is None


def test_rate_error_body_with_day_window() -> None:
    body = (
        '{"error":{"message":"Rate limit of 150 per 86400s exceeded for UserByModelByDay. '
        'Please wait 4301 seconds before retrying."}}'
    )
    err = parse_rate_error(body)
    assert err is not None
    assert (err.limit, err.period_s, err.scope) == (150, 86400, "UserByModelByDay")


def test_rate_error_body_without_match_is_none() -> None:
    assert parse_rate_error("nope") is None
    assert parse_rate_error("") is None


def test_burst_table_two_models_one_429() -> None:
    hdr = {"x-ratelimit-remaining-requests": "5", "x-ratelimit-limit-requests": "15"}
    records = [_rec("a/m1", i, headers=hdr) for i in range(1, 12)]
    records.append(_rec("a/m1", 12, status=429))
    records += [_rec("b/m2", i) for i in range(1, 4)]
    table = render_burst_table(records)
    assert "| a/m1 | 12 | first 429 at 12 | 5 | 15 |" in table
    assert "| b/m2 | 3 | none | n/a | n/a |" in table


def test_run_burst_stops_at_the_first_429_per_model() -> None:
    calls: list[tuple[str, int]] = []

    def send(model: str, index: int) -> Record:
        calls.append((model, index))
        return _rec(model, index, status=429 if (model == "m1" and index == 4) else 200)

    records = run_burst(send, ["m1", "m2"], max_requests=6)
    assert [r.index for r in records if r.model == "m1"] == [1, 2, 3, 4]
    assert [r.index for r in records if r.model == "m2"] == [1, 2, 3, 4, 5, 6]
    assert len(calls) == 10


def test_run_burst_never_exceeds_30_requests() -> None:
    sent = 0

    def send(model: str, index: int) -> Record:
        nonlocal sent
        sent += 1
        return _rec(model, index)

    run_burst(send, ["m1"], max_requests=500)
    assert sent == 30


def _hourly(model: str, n: int, first_429: int | None) -> list[Record]:
    rows = []
    for i in range(1, n + 1):
        status = 429 if first_429 is not None and i >= first_429 else 200
        rows.append(_rec(model, i, status=status, ts=f"2026-11-02T{i - 1:02d}:07:00+00:00"))
    return rows


def test_summarise_24_hourly_rows_with_429_at_row_20() -> None:
    summary = summarise_daily(_hourly("a/m1", 24, first_429=20))["a/m1"]
    assert summary.rows == 24
    assert summary.ok == 19
    assert summary.first_429_ts == "2026-11-02T19:07:00+00:00"
    assert summary.daily_limit == 19
    assert summary.source == "observed before first 429"


def test_summary_prefers_the_429_body_over_the_count() -> None:
    rows = _hourly("a/m1", 3, first_429=3)
    err = '{"error":{"message":"Rate limit of 150 per 86400s exceeded for UserByModelByDay."}}'
    rows[-1] = Record(**{**rows[-1].__dict__, "error": err})
    summary = summarise_daily(rows)["a/m1"]
    assert (summary.daily_limit, summary.source) == (150, "429 body")


def test_summary_uses_the_day_header_limit_first() -> None:
    rows = [_rec("a/m1", 1, headers={"x-ratelimit-limit-requests-day": "50"})]
    summary = summarise_daily(rows)["a/m1"]
    assert (summary.daily_limit, summary.source) == (50, "day header")


def test_summary_without_limit_info_is_n_a() -> None:
    summary = summarise_daily(_hourly("a/m1", 24, first_429=None))["a/m1"]
    assert summary.daily_limit is None
    assert summary.first_429_ts is None
    assert "n/a" in render_summary({"a/m1": summary}, per_pr=10, prs_per_day=8, nightly=60)


def test_budget_check_ten_calls_for_eight_prs_plus_nightly_vs_150() -> None:
    result = budget_check(limit=150, per_pr=10, prs_per_day=8, nightly=60)
    assert result.calls_per_day == 140
    assert result.allowed == 50
    assert result.fits is False


def test_budget_check_fits_when_within_a_third() -> None:
    assert budget_check(limit=1000, per_pr=10, prs_per_day=8, nightly=60).fits is True


def test_summary_table_reports_fits_no() -> None:
    summary = summarise_daily([_rec("a/m1", 1, headers={"x-ratelimit-limit-requests-day": "150"})])
    assert "fits: no" in render_summary(summary, per_pr=10, prs_per_day=8, nightly=60)


def test_load_records_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "daily.jsonl"
    rec = _rec("a/m1", 1, headers={"x-ratelimit-remaining-requests": "9"})
    path.write_text(json.dumps(rec.__dict__) + "\n\n", encoding="utf-8")
    assert load_records(path) == [rec]


@pytest.mark.network
@pytest.mark.live
def test_one_real_request_returns_rate_limit_headers() -> None:
    token = os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN")
    if not token:
        pytest.skip("PRUEFSTAND_GH_MODELS_TOKEN not set")
    send: Callable[[str, int], Record] = make_sender(token, timeout_s=30.0)
    record = send(os.environ.get("PRUEFSTAND_GH_MODELS_MODEL", "openai/gpt-4.1-mini"), 1)
    assert record.status in {200, 429}
    assert any(k.startswith("x-ratelimit-") for k in record.headers)


def _run_script(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "quota_probe.py"
    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PRUEFSTAND_GH_MODELS_TOKEN"}
    }
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("where", ["repo", "other"])
def test_script_runs_as_a_subprocess_from_any_cwd(where: str, tmp_path: Path) -> None:
    cwd = Path(__file__).resolve().parents[3] if where == "repo" else tmp_path
    helped = _run_script(cwd, "--help")
    assert helped.returncode == 0, helped.stderr
    assert "--burst" in helped.stdout
    sample = tmp_path / "daily.jsonl"
    rec = _rec("a/m1", 1, headers={"x-ratelimit-limit-requests-day": "150"})
    sample.write_text(json.dumps(rec.__dict__) + "\n", encoding="utf-8")
    summary = _run_script(cwd, "--summarise", str(sample))
    assert summary.returncode == 0, summary.stderr
    assert "| a/m1 |" in summary.stdout


def test_missing_token_exits_2_without_a_request(tmp_path: Path) -> None:
    proc = _run_script(tmp_path, "--daily", "--models", "a/m1")
    assert proc.returncode == 2
    assert "PRUEFSTAND_GH_MODELS_TOKEN" in proc.stderr


def test_run_burst_stops_after_two_consecutive_errors() -> None:
    sent: list[int] = []

    def send(model: str, index: int) -> Record:
        sent.append(index)
        return _rec(model, index, status=401)

    records = run_burst(send, ["m1", "m2"], max_requests=30)
    assert [r.index for r in records if r.model == "m1"] == [1, 2]
    assert len(sent) == 4


def test_a_single_error_does_not_stop_the_burst() -> None:
    def send(model: str, index: int) -> Record:
        return _rec(model, index, status=500 if index == 2 else 200)

    assert len(run_burst(send, ["m1"], max_requests=5)) == 5
