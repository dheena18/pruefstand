"""Can a stored baseline run be compared with a candidate run at all? (D1000).

The tier-1 workflow loads ``live-baseline`` from the last green push run of ``main``. When a merge
changes the ``eval_fingerprint`` on purpose (a metric version, a calibration epoch), that baseline
can never be paired again and, as only a green push run writes a new one, never gets replaced.
This module answers the question *before* ``pruefstand gate`` runs, so the workflow can treat such
a baseline like "no baseline" (a second run of the same commit). It decides nothing about pass or
fail: hard fails and absolute checks stay with the gate.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import StoreError
from pruefstand.store.artifacts import ArtifactStore


class FingerprintCheck(BaseModel):
    """Outcome of :func:`check_baseline_fingerprint`.

    Attributes:
        comparable: ``True`` when the baseline is readable and has the fingerprint of the candidate.
        baseline: The ``eval_fingerprint`` of the baseline (``""`` when it is unreadable).
        candidate: The ``eval_fingerprint`` of the candidate.
        reason: Empty when comparable, else one sentence for the PR comment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    comparable: bool
    baseline: str
    candidate: str
    reason: str


def _fingerprint(run_dir: Path) -> str:
    return ArtifactStore(run_dir.parent).read_run(run_dir).results.manifest.eval_fingerprint


def check_baseline_fingerprint(candidate: Path, baseline: Path) -> FingerprintCheck:
    """Compare the ``eval_fingerprint`` of a stored baseline run with that of the candidate.

    An unreadable baseline (artefact of an older schema, damaged download) is reported as not
    comparable, because it would keep ``main`` red for the same reason a changed fingerprint does.

    Args:
        candidate: Candidate run directory.
        baseline: Baseline run directory.

    Returns:
        The check. Equal fingerprints give ``comparable=True`` and an empty ``reason``; ``"aaa"``
        against ``"bbb"`` gives ``comparable=False`` and both values.

    Raises:
        StoreError: The candidate run cannot be read (a broken candidate must fail the job).
    """
    cand = _fingerprint(candidate)
    try:
        base = _fingerprint(baseline)
    except StoreError as exc:
        reason = f"baseline unreadable ({type(exc).__name__})"
        return FingerprintCheck(comparable=False, baseline="", candidate=cand, reason=reason)
    if base == cand:
        return FingerprintCheck(comparable=True, baseline=base, candidate=cand, reason="")
    reason = f"eval_fingerprint changed (baseline {base[:12]}, candidate {cand[:12]})"
    return FingerprintCheck(comparable=False, baseline=base, candidate=cand, reason=reason)
