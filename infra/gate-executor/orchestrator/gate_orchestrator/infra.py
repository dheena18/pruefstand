"""Infra failure mid-run and the one retry (Y5.2, D226, D245, D267, D274, N6.1, N6.4).

``llm-proxy`` ``GET /health`` is read before and after ``pruefstand run``; the differences go into
``RunManifest.counts`` (``model_reloads``, ``upstream_errors``) and any difference > 0 is an infra
error. An infra error posts ``set_check(sha, …, summary, infra_error=True)`` with
``"<kind>: <detail>; retrying once"``, runs ``health.sh --repair`` and retries once in the same
lock hold; a second infra error posts ``"…; re-dispatch to retry"`` and is recorded as processed
with ``result: "error"``.
``window_exceeded`` aborts (nightly) are never retried and post nothing here (T6.2b reports them).
"""

import subprocess
from collections.abc import Callable, Mapping

from gate_orchestrator.status import StatusPoster, infra_summary
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import PruefstandError

WINDOW_EXCEEDED = "window_exceeded"


class InfraError(PruefstandError):
    """An executor infrastructure failure; the message is ``"<kind>: <detail>"`` (D245)."""


# D1079: the only exceptions that count as infra (Ollama, tunnel, data root, proxy, health.sh).
# Candidate failures never raise here: the runner records them as case errors (TargetError stays
# inside the run), and any other exception is a bug that propagates.
INFRA_EXCEPTIONS: tuple[type[BaseException], ...] = (
    InfraError,
    OSError,
    subprocess.SubprocessError,
)


def _describe(exc: BaseException, *, repair: bool = False) -> str:
    if isinstance(exc, InfraError):
        return str(exc)
    if repair:
        return f"ollama_down: health.sh --repair failed ({type(exc).__name__})"
    return f"ollama_down: {type(exc).__name__} during the run"


def proxy_deltas(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    """``after - before`` for the two counted keys (the ``RunManifest.counts`` values).

    >>> proxy_deltas({"model_reloads": 2, "upstream_errors": 5, "requests": 100},
    ...              {"model_reloads": 2, "upstream_errors": 8, "requests": 900})
    {'model_reloads': 0, 'upstream_errors': 3}

    Raises:
        InfraError: a counter is missing or went backwards (the proxy restarted mid-run).
    """
    out: dict[str, int] = {}
    for key in ("model_reloads", "upstream_errors"):
        if key not in before or key not in after:
            msg = f"proxy_upstream: llm-proxy /health lacks {key}"
            raise InfraError(msg)
        delta = after[key] - before[key]
        if delta < 0:
            msg = f"proxy_upstream: llm-proxy {key} went backwards (proxy restarted during the run)"
            raise InfraError(msg)
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
            already reported the normal result); an ``INFRA_EXCEPTIONS`` raise counts as an infra
            error, any other exception propagates.
        repair: ``health.sh --repair`` under the held lock; an infra raise is the second failure.
        poster: status poster (``set_check(..., infra_error=True)`` here).
        record_error: appends the ``result: "error"`` line to ``processed.jsonl`` (second failure).

    Returns:
        The number of attempts made (1 or 2).
    """
    for number in (1, 2):
        try:
            infra_error = attempt(number)
        except INFRA_EXCEPTIONS as exc:
            infra_error = _describe(exc)
        if infra_error is None or infra_error.startswith(WINDOW_EXCEEDED):
            return number
        _post(poster, sha, infra_summary(infra_error, number))
        if number == 2:
            record_error(infra_summary(infra_error, 2))
            return number
        try:
            repair()
        except INFRA_EXCEPTIONS as exc:
            final = infra_summary(_describe(exc, repair=True), 2)
            _post(poster, sha, final)
            record_error(final)
            return number
    return 2


def _post(poster: StatusPoster, sha: str, summary: str) -> None:
    poster.set_check(sha, GateStatus.INSUFFICIENT_DATA, summary, infra_error=True)
