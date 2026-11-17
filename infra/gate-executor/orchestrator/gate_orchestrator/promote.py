"""Order and outcomes of a baseline promotion (T6.2b S3a, T6.1a D881, D321).

``baseline-promote.yml`` first runs ``pruefstand gate`` for a ``main`` / ``nightly-b<k>`` run and
only then ``pruefstand baseline promote``: promote refuses a run without a bound ``gate.json``
and a FAILed one (exit 1, D881). A release run (``release-b0..b2``) is never gated and goes straight
to promote. These helpers are pure: they build the argv lists and read the exit codes, the workflow
and the CLI run them. The owner's override of a failed gate is a manual step (runbook 3a) and never
appears here or in a workflow.
"""

from dataclasses import dataclass
from typing import Literal

from gate_orchestrator.window import BLOCKS, RELEASE_REFS

EXIT_OK = 0
EXIT_NOT_PROMOTED = 1
EXIT_INTEGRITY = 3
NIGHTLY_REFS = tuple(f"nightly-b{k}" for k in range(BLOCKS))
Status = Literal["promoted", "not_promoted", "integrity_error", "error"]


def valid_ref(ref: str) -> bool:
    """True for ``main``, ``nightly-b0..b2`` and ``release-b0..b2``."""
    return ref == "main" or ref in NIGHTLY_REFS or ref in RELEASE_REFS


def promotion_commands(run_dir: str, ref: str) -> list[list[str]]:
    """The argv lists to run, in order, to promote ``run_dir`` to ``ref``.

    ``main`` and ``nightly-b<k>``: the gate first, then promote. ``release-b<k>``: promote only.

    >>> [c[1] for c in promotion_commands("runs/r1", "main")]
    ['gate', 'baseline']
    >>> [c[1] for c in promotion_commands("runs/r1", "release-b1")]
    ['baseline']

    Raises:
        ValueError: ``ref`` is not one of the refs above.
    """
    if not valid_ref(ref):
        msg = f"cannot promote to ref {ref!r}"
        raise ValueError(msg)
    promote = ["pruefstand", "baseline", "promote", "--run", run_dir, "--ref", ref]
    if ref in RELEASE_REFS:
        return [promote]
    gate = ["pruefstand", "gate", "--candidate", run_dir, "--from-store", "--ref", ref]
    return [gate, promote]


@dataclass(frozen=True)
class PromoteOutcome:
    """What the workflow does with a promote exit code.

    Attributes:
        status: ``promoted``, ``not_promoted`` (refused), ``integrity_error`` or ``error``.
        record_processed: The run is recorded as processed (never retried on every poll).
        alert: The owner is alerted (integrity error).
        summary: One line for the job summary and the heartbeat.
    """

    status: Status
    record_processed: bool
    alert: bool
    summary: str


def interpret_promote_exit(code: int, run_id: str, ref: str) -> PromoteOutcome:
    """Map the exit code of ``pruefstand baseline promote`` (interfaces section 12).

    0 promoted; 1 refused (FAIL, hard fail, concurrent promote: "not promoted, reported", the same
    run is not retried); 3 integrity error (alert); anything else is a transient error, retried
    on the next poll.
    """
    if code == EXIT_OK:
        return PromoteOutcome(
            status="promoted",
            record_processed=True,
            alert=False,
            summary=f"promoted {run_id} to {ref}",
        )
    if code == EXIT_NOT_PROMOTED:
        return PromoteOutcome(
            status="not_promoted",
            record_processed=True,
            alert=False,
            summary=f"not promoted: {run_id} to {ref} (refused)",
        )
    if code == EXIT_INTEGRITY:
        return PromoteOutcome(
            status="integrity_error",
            record_processed=True,
            alert=True,
            summary=f"integrity error promoting {run_id} to {ref}",
        )
    return PromoteOutcome(
        status="error",
        record_processed=False,
        alert=False,
        summary=f"promote of {run_id} to {ref} failed (exit {code})",
    )
