"""Measure the GitHub Models free-tier quotas (T0.6 S6/S7, check C9).

Modes (token from the env var ``PRUEFSTAND_GH_MODELS_TOKEN``, never printed or stored):

* ``--burst``: up to 30 tiny requests per candidate model, stop at the first HTTP 429, record every
  ``x-ratelimit-*`` header; prints a Markdown table.
* ``--daily``: one tiny request per model, appended as JSONL (run hourly for 24 h, S7).
* ``--summarise FILE.jsonl``: measured daily limit per model and the budget check.

Every record is one JSON line: ``Record`` below. The tiny request asks for one token of output.

Example (budget check: 10 calls x 8 PRs + 60 nightly = 140 calls/day against a limit of 150;
the plan allows at most a third of the limit = 50 calls):
    >>> budget_check(limit=150, per_pr=10, prs_per_day=8, nightly=60).fits
    False
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

if __package__ in (
    None,
    "",
):  # run as `python scripts/models/quota_probe.py`: make `models` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.quota_model import (  # needs the sys.path line above
    BudgetResult,
    DailySummary,
    RateError,
    RateWindow,
    Record,
    budget_check,
    load_records,
    parse_rate_error,
    parse_rate_headers,
    render_burst_table,
    render_summary,
    summarise_daily,
)

__all__ = [
    "BudgetResult",
    "DailySummary",
    "RateError",
    "RateWindow",
    "Record",
    "budget_check",
    "load_records",
    "main",
    "make_sender",
    "parse_rate_error",
    "parse_rate_headers",
    "render_burst_table",
    "render_summary",
    "run_burst",
    "summarise_daily",
]

ENDPOINT = "https://models.github.ai/inference/chat/completions"
MAX_BURST = 30
# Candidate non-qwen models. UNVERIFIED ids (the catalogue could not be read when this was written;
# the Mistral id in particular may differ): a wrong id answers 4xx and stops after two requests.
DEFAULT_MODELS = (
    "openai/gpt-4.1-mini",
    "openai/gpt-4o-mini",
    "meta/Llama-3.3-70B-Instruct",
    "mistral-ai/Mistral-Small-3.1",
    "microsoft/Phi-4",
)
Sender = Callable[[str, int], Record]


def make_sender(token: str, timeout_s: float = 60.0) -> Sender:
    """Build the function that sends one tiny chat request and returns its ``Record``.

    Args:
        token: Models: read token (never logged).
        timeout_s: Per-request timeout.

    Returns:
        ``send(model, index)``; network errors become a record with ``status=0``.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def send(model: str, index: int) -> Record:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Antworte nur mit: ok"}],
            "max_tokens": 1,
        }
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(ENDPOINT, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            return Record(ts, model, index, 0, {}, None, type(exc).__name__)
        rate = {
            k.lower(): v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit-")
        }
        error = resp.text[:500] if resp.status_code != 200 else None
        return Record(
            ts, model, index, resp.status_code, rate, resp.headers.get("retry-after"), error
        )

    return send


def run_burst(send: Sender, models: Sequence[str], max_requests: int) -> list[Record]:
    """Send up to ``max_requests`` per model (cap 30, so at most 30 per model in total).

    A model stops at its first 429 and after two consecutive statuses other than 200 and 429
    (bad token, wrong model id), so a typo never burns the budget.

    Args:
        send: One-request function, see ``make_sender``.
        models: Candidate model ids.
        max_requests: Requests per model, capped at ``MAX_BURST``.

    Returns:
        All records in send order.
    """
    records: list[Record] = []
    for model in models:
        errors = 0
        for index in range(1, min(max_requests, MAX_BURST) + 1):
            record = send(model, index)
            records.append(record)
            if record.status == 429:
                break
            errors = errors + 1 if record.status != 200 else 0
            if errors >= 2:
                break
    return records


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--burst", action="store_true", help="up to 30 requests per model, stop at 429"
    )
    mode.add_argument("--daily", action="store_true", help="one request per model, append JSONL")
    mode.add_argument("--summarise", type=Path, metavar="JSONL", help="summarise a --daily file")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--max-requests", type=int, default=MAX_BURST)
    parser.add_argument("--out", type=Path, help="JSONL file for --burst and --daily records")
    parser.add_argument("--per-pr-calls", type=int, default=10)
    parser.add_argument("--prs-per-day", type=int, default=10)
    parser.add_argument("--nightly-calls", type=int, default=60)
    return parser


def _append(path: Path | None, records: Iterable[Record]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code (2 when the token is missing)."""
    args = _parser().parse_args(argv)
    if args.summarise is not None:
        summary = summarise_daily(load_records(args.summarise))
        sys.stdout.write(
            render_summary(summary, args.per_pr_calls, args.prs_per_day, args.nightly_calls)
        )
        return 0
    token = os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN")
    if not token:
        sys.stderr.write("PRUEFSTAND_GH_MODELS_TOKEN is not set (Models: read token)\n")
        return 2
    send = make_sender(token)
    if args.burst:
        records = run_burst(send, args.models, args.max_requests)
        sys.stdout.write(render_burst_table(records))
    else:
        records = [send(model, 1) for model in args.models]
        sys.stdout.write(render_burst_table(records))
    _append(args.out, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
