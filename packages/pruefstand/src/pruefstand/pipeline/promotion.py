"""``baseline promote`` guard: a run whose gate failed is not promoted by accident (D881, T6.1a).

``check_gate_for_promotion`` is called by ``pruefstand baseline promote`` before
``store.promote.prepare_promotion``. Who guarantees what: the promote command itself. It never
trusts a ``gate.json`` to be present (the release run is never gated), so it recomputes the hard
leaks (``rule == "hard_fail"``) of the verified run from the config's policy, and it reads
``gate.json`` when there is one (a leak check that could not run makes the gate FAIL, which the
status check covers).
"""

from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.config import GatePolicy
from pruefstand.core.enums import GateStatus
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


def _read_gate(run: Path, run_id: str) -> GateReport | None:
    """The run's ``gate.json`` or None when there is none.

    Raises:
        BaselineRefused: The file exists but cannot be read, is invalid, or belongs to another run
            (never waived by the override flag: it is no verdict about this run).
    """
    path = run / GATE_FILE
    try:
        raw = read_regular(path, _MAX_GATE_BYTES)
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f"{path} cannot be read ({exc.__class__.__name__}); not promoted"
        raise BaselineRefused(msg) from None
    try:
        report = GateReport.model_validate_json(raw[:_MAX_GATE_BYTES])
    except (ValidationError, ValueError):
        report = None
    if report is None or len(raw) > _MAX_GATE_BYTES:
        msg = f"{path} is not a valid gate report; not promoted"
        raise BaselineRefused(msg)
    if report.candidate_run_id != run_id:
        msg = f"{path} is the gate result of run {report.candidate_run_id}, not of {run_id}"
        raise BaselineRefused(msg)
    return report


def check_gate_for_promotion(
    run: Path, results: RunResults, policy: GatePolicy, *, allow_failed_gate: bool
) -> None:
    """Refuse a run whose gate FAILed or that has a hard fail, unless the override is given.

    Args:
        run: The run directory (``gate.json`` is optional: main and nightly runs are gated, the
            release run is not).
        results: The verified run read from ``run``.
        policy: The gate policy of the config (its ``hard_fail`` metrics are recomputed).
        allow_failed_gate: The owner's explicit ``--allow-failed-gate``; waives a FAIL and
            hard fails, never a ``gate.json`` that is invalid or of another run.

    Raises:
        BaselineRefused: Gate FAIL or hard fail without the override, or an unusable ``gate.json``.
    """
    run_id = str(results.manifest.run_id)
    report = _read_gate(run, run_id)
    reasons: list[str] = []
    if report is not None and report.status is GateStatus.FAIL:
        reasons.append(f"its gate result is FAIL ({GATE_FILE})")
    leaks = find_hard_fails(results, policy.hard_fail)
    found = {f.metric for f in leaks if f.rule == "hard_fail"}  # unverifiable ones FAIL the gate
    if found:
        reasons.append(f"it has hard fails ({', '.join(sorted(found))})")
    if not reasons:
        return
    text = f"run {run_id}: {' and '.join(reasons)}"
    if not allow_failed_gate:
        msg = f"{text}; not promoted (the owner can pass {OVERRIDE_FLAG})"
        raise BaselineRefused(msg)
    _log.warning("promote_failed_gate_overridden", run_id=run_id, reasons=reasons)
