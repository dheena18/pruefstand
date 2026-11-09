"""``baseline promote`` guard: a run whose gate failed is not promoted by accident (D881, T6.1a).

``check_gate_for_promotion`` is called by ``pruefstand baseline promote`` after
``store.promote.prepare_promotion``. Who guarantees what: the promote command itself.

* ``main`` and ``nightly-b<k>`` runs are gated, so their ``gate.json`` is REQUIRED (absent: refused,
  exit 1, "run the gate first"). The release anchors ``release-b<k>`` are never gated and may be
  promoted without one.
* A ``gate.json`` that is unreadable, invalid or of another run is an integrity error (exit 3).
* Status FAIL, or any hard-fail finding recomputed from the verified run with the config's policy
  (a leak, or a leak check that could not run), is refused (exit 1) unless the owner passes
  ``--allow-failed-gate``. The override never waives a missing or unusable ``gate.json``.
"""

from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.config import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import StoreIntegrityError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.gate.hard_fail import find_hard_fails
from pruefstand.pipeline._files import read_regular
from pruefstand.pipeline.gate import GATE_FILE
from pruefstand.store.promote import BaselineRefused

_log = get_logger(__name__)
_MAX_GATE_BYTES = 16 * 1024 * 1024
OVERRIDE_FLAG = "--allow-failed-gate"
RELEASE_PREFIX = "release-"


def _read_gate(run: Path, run_id: str) -> GateReport | None:
    """The run's ``gate.json`` or None when there is none.

    Raises:
        StoreIntegrityError: The file exists but cannot be read (also a symlink or a directory),
            is invalid, or belongs to another run.
    """
    path = run / GATE_FILE
    try:
        raw = read_regular(path, _MAX_GATE_BYTES, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f"{path} cannot be read ({exc.__class__.__name__}); not promoted"
        raise StoreIntegrityError(msg) from None
    try:
        report = GateReport.model_validate_json(raw[:_MAX_GATE_BYTES])
    except (ValidationError, ValueError):
        report = None
    if report is None or len(raw) > _MAX_GATE_BYTES:
        msg = f"{path} is not a valid gate report; not promoted"
        raise StoreIntegrityError(msg)
    if report.candidate_run_id != run_id:
        msg = f"{path} is the gate result of run {report.candidate_run_id}, not of {run_id}"
        raise StoreIntegrityError(msg)
    return report


def _reasons(report: GateReport | None, results: RunResults, policy: GatePolicy) -> list[str]:
    reasons: list[str] = []
    if report is not None and report.status is GateStatus.FAIL:
        reasons.append(f"its gate result is FAIL ({GATE_FILE})")
    findings = find_hard_fails(results, policy.hard_fail)
    if findings:
        names = sorted({f"{f.metric} ({f.rule})" for f in findings})
        reasons.append(f"it has hard-fail findings: {', '.join(names)}")
    return reasons


def check_gate_for_promotion(
    run: Path, results: RunResults, policy: GatePolicy, *, ref: str, allow_failed_gate: bool
) -> None:
    """Refuse a run whose gate FAILed or that has a hard-fail finding, unless overridden.

    Args:
        run: The run directory.
        results: The verified run read from ``run``.
        policy: The gate policy of the config (its ``hard_fail`` metrics are recomputed).
        ref: The target ref; ``release-b<k>`` may lack a ``gate.json``, every other ref may not.
        allow_failed_gate: The owner's explicit ``--allow-failed-gate``; waives a FAIL and
            hard-fail findings, never a missing or unusable ``gate.json``.

    Raises:
        BaselineRefused: No ``gate.json`` for a gated ref, or FAIL / hard fails without the
            override (exit 1).
        StoreIntegrityError: ``gate.json`` is unreadable, invalid or of another run (exit 3).
    """
    run_id = str(results.manifest.run_id)
    report = _read_gate(run, run_id)
    if report is None and not ref.startswith(RELEASE_PREFIX):
        msg = f"run {run_id} has no {GATE_FILE}: run `pruefstand gate` for it before promoting"
        raise BaselineRefused(msg)
    reasons = _reasons(report, results, policy)
    if not reasons:
        return
    text = f"run {run_id}: {' and '.join(reasons)}"
    if not allow_failed_gate:
        msg = f"{text}; not promoted (the owner can pass {OVERRIDE_FLAG})"
        raise BaselineRefused(msg)
    _log.warning("promote_failed_gate_overridden", run_id=run_id, reasons=reasons)
