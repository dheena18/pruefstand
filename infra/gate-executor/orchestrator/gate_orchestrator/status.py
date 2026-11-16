"""Commit-status texts and the poster protocol (interfaces §10, R13 P4.2, D226, D274, D288).

Gate results go through ``set_check`` (the single mapping table); every non-result state goes
through ``post_status``. Statuses of non-gated PRs come only from ``gate-router.yml`` (P4.2).
``pruefstand.report.github.GitHubPublisher`` (T1.9) satisfies :class:`StatusPoster`.
"""

from typing import Literal, Protocol

from pruefstand.core.enums import GateStatus

State = Literal["pending", "success", "failure", "error"]
GATE_CONTEXT = "pruefstand/gate"
MAINTENANCE = "executor in maintenance; dispatch again later"
BUSY = "executor busy (GPU lock held); dispatch again"
RETRYING = "retrying once"
MAX_DESCRIPTION = 140  # GitHub commit-status description limit
INFRA_PREFIX = "executor infra error: "  # interfaces §10, added by set_check(..., infra_error=True)
REDISPATCH = "re-dispatch to retry"


class StatusPoster(Protocol):
    """The two status calls of ``GitHubPublisher`` the orchestrator uses."""

    def post_status(
        self, sha: str, state: State, description: str, context: str = GATE_CONTEXT
    ) -> None:
        """Low-level commit status (``pending`` / preflight ``error``)."""

    def set_check(
        self,
        sha: str,
        status: GateStatus,
        summary: str,
        *,
        no_baseline: bool = False,
        infra_error: bool = False,
    ) -> None:
        """Gate result through the interfaces §10 mapping table."""


def unhealthy(reason: str) -> str:
    """Preflight failure text: ``"executor unhealthy: <reason>"``."""
    return f"executor unhealthy: {reason}"


def infra_summary(infra_error: str, attempt: int) -> str:
    """``set_check`` summary of an infra failure: 1st → ``; retrying once``, 2nd → re-dispatch.

    The infra text is shortened (``…``) so that ``"executor infra error: <summary>"`` fits GitHub's
    140 characters with the ending intact (D1086); ``run.json`` keeps the full ``infra_error``.

    >>> infra_summary("proxy_upstream: 3 upstream errors", 1)
    'proxy_upstream: 3 upstream errors; retrying once'

    Raises:
        ValueError: ``attempt`` is not 1 or 2 (there is exactly one retry).
    """
    if attempt not in (1, 2):
        msg = "attempt must be 1 or 2"
        raise ValueError(msg)
    ending = f"; {RETRYING if attempt == 1 else REDISPATCH}"
    room = (
        MAX_DESCRIPTION - len(INFRA_PREFIX) - len(ending)
    )  # D1086: the ending is what owners act on
    if len(infra_error) > room:
        infra_error = infra_error[: room - 1].rstrip() + "…"
    return f"{infra_error}{ending}"
