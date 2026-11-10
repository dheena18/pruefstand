"""``baseline promote`` guard: a run whose gate failed is not promoted by accident (D881, T6.1a).

``check_gate_for_promotion`` is called by ``pruefstand baseline promote`` after
``store.promote.prepare_promotion``. Who guarantees what: the promote command itself.

* ``main`` and ``nightly-b<k>`` runs are gated, so their ``gate.json`` is REQUIRED (absent: refused,
  exit 1, "run the gate first"). The release anchors ``release-b<k>`` are never gated and may be
  promoted without one.
* A ``gate.json`` that is unreadable, invalid, of another run or of another ``eval_fingerprint``
  is an integrity error (exit 3).
* For a gated ref the ``gate.json`` must be bound to the baseline that is stored now for
  (fingerprint, ref) (review F1, D1120): a self-gate (baseline = candidate) and a comparison with
  any other run are refused (exit 1) and never waived. A ``no_baseline`` report fits only the
  first promote of (fingerprint, ref); once a baseline is stored it is refused like FAIL.
* Status FAIL or INSUFFICIENT_DATA, or any hard-fail finding recomputed from the verified run with
  the config's policy (a leak, or a leak check that could not run), is refused (exit 1) unless the
  owner passes ``--allow-failed-gate``. The override never waives a missing, unusable or unbound
  ``gate.json``.
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


def _read_gate(run: Path, run_id: str, fingerprint: str) -> GateReport | None:
    """The run's ``gate.json`` or None when there is none.

    Raises:
        StoreIntegrityError: The file exists but cannot be read (also a symlink or a directory),
            is invalid, or belongs to another run or another ``eval_fingerprint``.
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
    if report.eval_fingerprint != fingerprint:
        msg = f"{path} is for eval_fingerprint {report.eval_fingerprint}, not {fingerprint}"
        raise StoreIntegrityError(msg)
    return report


def _check_binding(report: GateReport, run_id: str, current: str | None) -> None:
    """Refuse a ``gate.json`` that was not decided against the stored baseline (never waived)."""
    against = report.baseline_run_id
    if against is not None and str(against) == run_id:
        msg = f"run {run_id}: its {GATE_FILE} compares the run against itself; not promoted"
        raise BaselineRefused(msg)
    if against is None and current is not None:
        msg = (
            f"run {run_id}: its {GATE_FILE} was decided with no baseline, but {current} is stored;"
            " run `pruefstand gate` against the current baseline; not promoted"
        )
        raise BaselineRefused(msg)
    if against is None or (current is not None and str(against) == current):
        return
    stored = f"the stored baseline is {current}" if current else "no baseline is stored"
    msg = (
        f"run {run_id}: its {GATE_FILE} compares with {against}, not the stored baseline"
        f" ({stored}); run `pruefstand gate` against the current baseline; not promoted"
    )
    raise BaselineRefused(msg)


def _status_reasons(report: GateReport | None, *, gated: bool) -> list[str]:
    if report is None:
        return []
    if report.status is GateStatus.FAIL:
        return [f"its gate result is FAIL ({GATE_FILE})"]
    if not gated:
        return []
    if report.status is GateStatus.INSUFFICIENT_DATA and not report.no_baseline:
        return [f"its gate result is INSUFFICIENT_DATA ({GATE_FILE})"]
    if report.status is GateStatus.UNSUPPORTED_CONFIG:
        return [f"its gate result is UNSUPPORTED_CONFIG ({GATE_FILE})"]
    return []


def _reasons(
    report: GateReport | None,
    results: RunResults,
    policy: GatePolicy,
    *,
    gated: bool,
) -> list[str]:
    reasons = _status_reasons(report, gated=gated)
    findings = find_hard_fails(results, policy.hard_fail)
    if findings:
        names = sorted({f"{f.metric} ({f.rule})" for f in findings})
        reasons.append(f"it has hard-fail findings: {', '.join(names)}")
    return reasons


def check_gate_for_promotion(
    run: Path,
    results: RunResults,
    policy: GatePolicy,
    *,
    ref: str,
    allow_failed_gate: bool,
    current: str | None,
) -> list[str]:
    """Refuse a run whose gate FAILed or that has a hard-fail finding, unless overridden.

    Args:
        run: The run directory.
        results: The verified run read from ``run``.
        policy: The gate policy of the config (its ``hard_fail`` metrics are recomputed).
        ref: The target ref; ``release-b<k>`` may lack a ``gate.json``, every other ref may not.
        allow_failed_gate: The owner's explicit ``--allow-failed-gate``; waives FAIL,
            INSUFFICIENT_DATA, a ``no_baseline`` report after the first promote and hard-fail
            findings, never a missing, unusable or unbound ``gate.json``.
        current: Run id of the baseline stored now for (fingerprint, ``ref``), None when there
            is none (the first promote). Ignored for ``release-b<k>``.

    Raises:
        BaselineRefused: No ``gate.json`` for a gated ref, a ``gate.json`` not bound to
            ``current`` (or a self-gate), or FAIL / INSUFFICIENT_DATA / a stale ``no_baseline``
            report / hard fails without the override (exit 1).
        StoreIntegrityError: ``gate.json`` is unreadable, invalid, of another run or of another
            fingerprint (exit 3).

    Returns:
        The reasons the owner's override waived (empty when nothing was waived); the caller
        records them with the baseline (D1123).
    """
    run_id = str(results.manifest.run_id)
    report = _read_gate(run, run_id, results.manifest.eval_fingerprint)
    gated = not ref.startswith(RELEASE_PREFIX)
    if report is None and gated:
        msg = f"run {run_id} has no {GATE_FILE}: run `pruefstand gate` for it before promoting"
        raise BaselineRefused(msg)
    if report is not None and gated:
        _check_binding(report, run_id, current)
    reasons = _reasons(report, results, policy, gated=gated)
    if not reasons:
        return []
    text = f"run {run_id}: {' and '.join(reasons)}"
    if not allow_failed_gate:
        msg = f"{text}; not promoted (the owner can pass {OVERRIDE_FLAG})"
        raise BaselineRefused(msg)
    _log.warning("promote_failed_gate_overridden", run_id=run_id, reasons=reasons)
    return reasons
