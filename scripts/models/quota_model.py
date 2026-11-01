"""Records, rate-limit parsing, tables, daily summary and budget check of the quota probe (T0.6).

Pure functions (no network); `quota_probe.py` holds the HTTP sender and the CLI.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_HEADER = re.compile(
    r"^x-ratelimit-(limit|remaining|reset)(?:-(requests|tokens))?(?:-(second|minute|hour|day))?$"
)
_ERROR = re.compile(r"Rate limit of (\d+) per (\d+)s exceeded for (\w+)")


@dataclass(frozen=True)
class RateWindow:
    """One rate-limit window parsed from the response headers."""

    resource: str
    window: str | None
    limit: int | None
    remaining: int | None
    reset: str | None


@dataclass(frozen=True)
class RateError:
    """The numbers in a 429 body: ``Rate limit of 150 per 86400s exceeded for UserByModelByDay``."""

    limit: int
    period_s: int
    scope: str


@dataclass(frozen=True)
class Record:
    """One probe request (a JSONL line); ``headers`` holds only ``x-ratelimit-*`` headers."""

    ts: str
    model: str
    index: int
    status: int
    headers: dict[str, str]
    retry_after: str | None
    error: str | None


@dataclass(frozen=True)
class DailySummary:
    """Measured quota of one model over a series of rows."""

    rows: int
    ok: int
    first_429_ts: str | None
    daily_limit: int | None
    source: str


@dataclass(frozen=True)
class BudgetResult:
    """Planned calls per day against a third of the measured daily limit."""

    calls_per_day: int
    allowed: int
    fits: bool


def _int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_rate_headers(headers: Mapping[str, str]) -> dict[str, RateWindow]:
    """Group ``x-ratelimit-*`` headers into windows.

    Args:
        headers: Response headers (any case).

    Returns:
        ``{"requests": ..., "requests-day": ..., "tokens-minute": ...}``; a header without a
        resource counts as ``requests``, one without a window has ``window=None``.
    """
    parts: dict[str, dict[str, str]] = {}
    meta: dict[str, tuple[str, str | None]] = {}
    for name, value in headers.items():
        match = _HEADER.match(name.lower())
        if match is None:
            continue
        kind, resource, window = match.group(1), match.group(2) or "requests", match.group(3)
        key = resource if window is None else f"{resource}-{window}"
        parts.setdefault(key, {})[kind] = value
        meta[key] = (resource, window)
    return {
        key: RateWindow(
            resource=meta[key][0],
            window=meta[key][1],
            limit=_int(vals["limit"]) if "limit" in vals else None,
            remaining=_int(vals["remaining"]) if "remaining" in vals else None,
            reset=vals.get("reset"),
        )
        for key, vals in parts.items()
    }


def parse_rate_error(body: str) -> RateError | None:
    """Read limit, period and scope from a 429 body, or ``None`` when it has another shape."""
    match = _ERROR.search(body or "")
    if match is None:
        return None
    return RateError(int(match.group(1)), int(match.group(2)), match.group(3))


def _remaining_limit(record: Record) -> tuple[str, str]:
    windows = parse_rate_headers(record.headers)
    chosen = next(iter(windows.values()), None)
    if chosen is None:
        return "n/a", "n/a"
    remaining = "n/a" if chosen.remaining is None else str(chosen.remaining)
    limit = "n/a" if chosen.limit is None else str(chosen.limit)
    return remaining, limit


def render_burst_table(records: Iterable[Record]) -> str:
    """Markdown table per model: requests, first 429, last remaining, limit (n/a if absent)."""
    by_model: dict[str, list[Record]] = {}
    for record in records:
        by_model.setdefault(record.model, []).append(record)
    rows = [
        "| model | requests | first 429 | remaining (last ok) | limit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model, recs in by_model.items():
        first = next((r.index for r in recs if r.status == 429), None)
        ok = [r for r in recs if r.status == 200]
        remaining, limit = _remaining_limit(ok[-1]) if ok else ("n/a", "n/a")
        label = "none" if first is None else f"first 429 at {first}"
        rows.append(f"| {model} | {len(recs)} | {label} | {remaining} | {limit} |")
    return "\n".join(rows) + "\n"


def load_records(path: Path) -> list[Record]:
    """Read a JSONL file written by ``--daily`` (blank lines are skipped)."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(Record(**json.loads(line)))
    return records


def _day_limit(records: list[Record]) -> tuple[int | None, str]:
    for record in records:
        window = parse_rate_headers(record.headers).get("requests-day")
        if window is not None and window.limit is not None:
            return window.limit, "day header"
    for record in records:
        err = parse_rate_error(record.error or "") if record.status == 429 else None
        if err is not None and err.period_s >= 86400:
            return err.limit, "429 body"
    first = next((i for i, r in enumerate(records) if r.status == 429), None)
    if first is not None:
        return sum(1 for r in records[:first] if r.status == 200), "observed before first 429"
    return None, "n/a"


def summarise_daily(records: Iterable[Record]) -> dict[str, DailySummary]:
    """Measured daily limit per model: day header, else 429 body, else successes before the 429."""
    by_model: dict[str, list[Record]] = {}
    for record in sorted(records, key=lambda r: r.ts):
        by_model.setdefault(record.model, []).append(record)
    out: dict[str, DailySummary] = {}
    for model, recs in by_model.items():
        limit, source = _day_limit(recs)
        first_429 = next((r.ts for r in recs if r.status == 429), None)
        out[model] = DailySummary(
            rows=len(recs),
            ok=sum(1 for r in recs if r.status == 200),
            first_429_ts=first_429,
            daily_limit=limit,
            source=source,
        )
    return out


def budget_check(limit: int, per_pr: int, prs_per_day: int, nightly: int) -> BudgetResult:
    """Check ``per_pr x prs_per_day + nightly`` calls per day against a third of ``limit``."""
    calls = per_pr * prs_per_day + nightly
    allowed = limit // 3
    return BudgetResult(calls, allowed, calls <= allowed)


def render_summary(
    summary: Mapping[str, DailySummary], per_pr: int, prs_per_day: int, nightly: int
) -> str:
    """Markdown table of the measured daily limits and the budget check per model."""
    rows = [
        "| model | rows | ok | first 429 | daily limit | source | budget |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for model, s in summary.items():
        if s.daily_limit is None:
            budget = "n/a"
        else:
            b = budget_check(s.daily_limit, per_pr, prs_per_day, nightly)
            verdict = "yes" if b.fits else "no"
            budget = f"{b.calls_per_day} calls vs {b.allowed} allowed (1/3): fits: {verdict}"
        limit = "n/a" if s.daily_limit is None else str(s.daily_limit)
        rows.append(
            f"| {model} | {s.rows} | {s.ok} | {s.first_429_ts or 'none'} | {limit} | "
            f"{s.source} | {budget} |"
        )
    return "\n".join(rows) + "\n"
