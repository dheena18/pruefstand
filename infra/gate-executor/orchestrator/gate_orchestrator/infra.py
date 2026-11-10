"""Infra failure mid-run and the one retry (Y5.2, D226, D245, D267, D274, N6.1, N6.4).

``llm-proxy`` ``GET /health`` is read before and after ``pruefstand run``; the differences go into
``RunManifest.counts`` (``model_reloads``, ``upstream_errors``) and any difference > 0 is an infra
error. An infra error posts ``set_check(sha, …, summary, infra_error=True)`` with
``"<kind>: <detail>; retrying once"``, runs ``health.sh --repair`` and retries once in the same
lock hold; a second infra error posts ``"…; re-dispatch to retry"`` and is recorded as processed
with ``result: "error"``.
``window_exceeded`` aborts (nightly) are never retried and post nothing here (T6.2b reports them).
"""

from collections.abc import Callable, Mapping

from gate_orchestrator.status import StatusPoster, infra_summary
from pruefstand.core.enums import GateStatus

WINDOW_EXCEEDED = "window_exceeded"


def proxy_deltas(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    """``after - before`` for the two counted keys (the ``RunManifest.counts`` values).

    >>> proxy_deltas({"model_reloads": 2, "upstream_errors": 5, "requests": 100},
    ...              {"model_reloads": 2, "upstream_errors": 8, "requests": 900})
    {'model_reloads': 0, 'upstream_errors': 3}

    Raises:
        ValueError: a counter is missing or went backwards (the proxy restarted mid-run).
    """
    out: dict[str, int] = {}
    for key in ("model_reloads", "upstream_errors"):
        if key not in before or key not in after:
            msg = f"llm-proxy /health lacks {key}"
            raise ValueError(msg)
        delta = after[key] - before[key]
        if delta < 0:
            msg = f"llm-proxy {key} went backwards (proxy restarted during the run)"
            raise ValueError(msg)
        out[key] = delta
    return out


def infra_from_deltas(deltas: Mapping[str, int]) -> str | None:
    """``proxy_upstream: …`` / ``model_reload: …`` for a positive delta (upstream first)."""
    if deltas.get("upstream_errors", 0) > 0:
        return f"proxy_upstream: {deltas['upstream_errors']} upstream errors during the run"
    if deltas.get("model_reloads", 0) > 0:
        return f"model_reload: {deltas['model_reloads']} model reloads during the run"
    return None


def run_with_retry(
    sha: str,
    attempt: Callable[[int], str | None],
    *,
    repair: Callable[[], None],
    poster: StatusPoster,
    record_error: Callable[[str], None],
) -> int:
    """Run ``attempt(1)``; on an infra error report it, repair and run ``attempt(2)`` once.

    Args:
        sha: the gated SHA.
        attempt: runs the job; returns the run's ``infra_error`` or ``None`` (then the caller has
            already reported the normal result).
        repair: ``health.sh --repair`` under the held lock.
        poster: status poster (``set_check(..., infra_error=True)`` here).
        record_error: appends the ``result: "error"`` line to ``processed.jsonl`` (second failure).

    Returns:
        The number of attempts made (1 or 2).
    """
    for number in (1, 2):
        infra_error = attempt(number)
        if infra_error is None or infra_error.startswith(WINDOW_EXCEEDED):
            return number
        summary = infra_summary(infra_error, number)
        poster.set_check(sha, GateStatus.INSUFFICIENT_DATA, summary, infra_error=True)
        if number == 2:
            record_error(summary)
            return number
        repair()
    return 2
