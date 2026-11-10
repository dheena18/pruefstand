"""Posting the gate result and pending states only on change (S8; interfaces §10, X4.6, P4.2).

GitHub keeps at most 1 000 statuses per SHA and context, so a status is posted only when its state
or description differs from the current ``pruefstand/gate`` status (read from the combined status
first). Gate results go through ``set_check`` (``no_baseline`` → ``failure`` "no baseline for <fp>;
run baseline-promote", never ``success``); every other state through ``post_status``. Fork jobs
post to the gated (mirrored) SHA only: the caller passes ``Job.sha``.
"""

from collections.abc import Mapping, Sequence

from gate_orchestrator.status import GATE_CONTEXT, State, StatusPoster
from pruefstand.core.enums import GateStatus
from pruefstand.report.github import status_for, truncate


def current_gate_status(statuses: Sequence[Mapping[str, object]]) -> tuple[str, str] | None:
    """``(state, description)`` of ``pruefstand/gate`` in a combined-status ``statuses`` list."""
    for item in statuses:
        if item.get("context") == GATE_CONTEXT:
            return str(item.get("state", "")), str(item.get("description", ""))
    return None


def _unchanged(current: tuple[str, str] | None, state: str, description: str) -> bool:
    return current == (state, truncate(description))


def post_gate_result(
    poster: StatusPoster,
    sha: str,
    *,
    status: GateStatus,
    summary: str,
    no_baseline: bool,
    current: tuple[str, str] | None,
) -> bool:
    """Post a gate result through ``set_check`` unless the same status is already set.

    Args:
        poster: status poster.
        sha: the gated SHA (the mirrored head for forks).
        status: ``GateReport.status``.
        summary: one-line summary; the ``eval_fingerprint`` when ``no_baseline``.
        no_baseline: ``GateReport.no_baseline`` (W2.4, D103).
        current: :func:`current_gate_status` of ``sha``.

    Returns:
        True when a status was posted.
    """
    state, description = status_for(status, summary, no_baseline=no_baseline, infra_error=False)
    if _unchanged(current, state, description):
        return False
    poster.set_check(sha, status, summary, no_baseline=no_baseline)
    return True


def post_state(
    poster: StatusPoster, sha: str, state: State, description: str, current: tuple[str, str] | None
) -> bool:
    """``post_status`` for a non-result state (pending, preflight error) unless already set."""
    if _unchanged(current, state, description):
        return False
    poster.post_status(sha, state, description)
    return True
