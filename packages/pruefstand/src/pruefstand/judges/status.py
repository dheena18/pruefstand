"""``judges/data/calibration_status.yaml`` (T5.4 writes it): what the calibration found.

Shape (T5.4, D930)::

    epoch: 1                  # judge_epoch, part of eval_fingerprint; only a passing
    re-calibration bumps it
    passed: false             # false: no judge passed, judged metrics are informational
    refusal_judged: {passed: true}   # the refusal judge may decide ambiguous answers
    judges:                   # per pinned judge (optional; T5.4 S11)
      ollama/gemma3:12b: {serving: "...", drift_threshold: 5, a0: 0.98, metrics: {...}}

A missing file means "not calibrated yet": the refusal judge is off and nothing is marked
uncalibrated (the file is T5.4's, no verdict exists before it).
"""

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from pruefstand.core.errors import ConfigError

FILE = "calibration_status.yaml"
_MAX_BYTES = 100_000


@dataclass(frozen=True)
class CalibrationStatus:
    """The calibration result: ``passed`` is None when the file says nothing about it.

    Attributes:
        passed: Whether a gating judge passed the pass rule (D146); None when unset.
        refusal_passed: Whether ``refusal_judged`` passed its rule (D193).
        drift_thresholds: Per judge model id, the minimum number of changed anchor verdicts that
            is drift (D308); a judge without an entry uses the default rule of ``is_drift``.
        self_agreement: Per judge model id, the anchor self-agreement ``a0`` (recorded only, D253).
    """

    passed: bool | None
    refusal_passed: bool
    drift_thresholds: dict[str, int] = field(default_factory=dict)
    self_agreement: dict[str, float] = field(default_factory=dict)


def _raw(path: Path | None) -> bytes | None:
    if path is None:
        resource = resources.files("pruefstand.judges") / "data" / FILE
        return resource.read_bytes() if resource.is_file() else None
    return path.read_bytes() if path.is_file() else None


def _per_judge(data: dict[object, object]) -> tuple[dict[str, int], dict[str, float]]:
    judges = data.get("judges")
    thresholds: dict[str, int] = {}
    agreement: dict[str, float] = {}
    if not isinstance(judges, dict):
        return thresholds, agreement
    for model, entry in judges.items():
        if not isinstance(entry, dict):
            continue
        threshold = entry.get("drift_threshold")
        if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0:
            thresholds[str(model)] = threshold
        a0 = entry.get("a0")
        if isinstance(a0, int | float) and not isinstance(a0, bool):
            agreement[str(model)] = float(a0)
    return thresholds, agreement


def read_status(path: Path | None = None) -> CalibrationStatus | None:
    """Read the status file; None when it does not exist.

    Args:
        path: The file; default the shipped ``judges/data/calibration_status.yaml``.

    Raises:
        ConfigError: The file exists but is too large, not YAML or not a mapping.
    """
    raw = _raw(path)
    if raw is None:
        return None
    try:
        data = yaml.safe_load(raw) if len(raw) <= _MAX_BYTES else None
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        msg = f"{FILE}: expected a mapping of at most {_MAX_BYTES} bytes"
        raise ConfigError(msg)
    passed = data.get("passed")
    refusal = data.get("refusal_judged")
    refusal_passed = isinstance(refusal, dict) and refusal.get("passed") is True
    thresholds, agreement = _per_judge(data)
    return CalibrationStatus(
        passed if isinstance(passed, bool) else None, refusal_passed, thresholds, agreement
    )


def refusal_judge_passed(path: Path | None = None) -> bool:
    """Whether T5.4 marked the refusal judge as passing (False without the file)."""
    status = read_status(path)
    return status is not None and status.refusal_passed


def judges_uncalibrated(path: Path | None = None) -> bool:
    """Whether T5.4 found no passing judge (``passed: false``); False without the file."""
    status = read_status(path)
    return status is not None and status.passed is False


def drift_threshold_of(model: str, path: Path | None = None) -> int | None:
    """Return the calibrated drift threshold of ``model`` (D308), None without one."""
    status = read_status(path)
    return None if status is None else status.drift_thresholds.get(model)
