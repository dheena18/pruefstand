"""``judges/data/calibration_status.yaml`` (T5.4 writes it): what the calibration found.

Shape::

    epoch: 2                  # judge epoch, part of eval_fingerprint
    passed: true              # false: no judge passed, judged metrics are informational
    refusal_judged: {passed: true}   # the refusal judge may decide ambiguous answers

A missing file means "not calibrated yet": the refusal judge is off and nothing is marked
uncalibrated (the file is T5.4's, no verdict exists before it).
"""

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from pruefstand.core.errors import ConfigError

FILE = "calibration_status.yaml"
_MAX_BYTES = 100_000


@dataclass(frozen=True)
class CalibrationStatus:
    """The calibration result: ``passed`` is None when the file says nothing about it."""

    passed: bool | None
    refusal_passed: bool


def read_status(path: Path | None = None) -> CalibrationStatus | None:
    """Read the status file; None when it does not exist.

    Args:
        path: The file; default the shipped ``judges/data/calibration_status.yaml``.

    Raises:
        ConfigError: The file exists but is too large, not YAML or not a mapping.
    """
    if path is None:
        resource = resources.files("pruefstand.judges") / "data" / FILE
        if not resource.is_file():
            return None
        raw = resource.read_bytes()
    else:
        if not path.is_file():
            return None
        raw = path.read_bytes()
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
    return CalibrationStatus(passed if isinstance(passed, bool) else None, refusal_passed)


def refusal_judge_passed(path: Path | None = None) -> bool:
    """Whether T5.4 marked the refusal judge as passing (False without the file)."""
    status = read_status(path)
    return status is not None and status.refusal_passed


def judges_uncalibrated(path: Path | None = None) -> bool:
    """Whether T5.4 found no passing judge (``passed: false``); False without the file."""
    status = read_status(path)
    return status is not None and status.passed is False
