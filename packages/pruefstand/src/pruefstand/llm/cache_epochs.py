"""Judge cache epochs and the drift flag file (T5.1 S13, D114, round 9 X3.3).

The *cache epoch* of a model is a suffix of ``model_version`` in the LLM cache key: bumping it makes
every cached verdict of that judge miss. It is **not** ``judge_epoch`` (that one only a successful
re-calibration bumps, T5.4) and it never enters ``eval_fingerprint``.

Files in ``cache_dir``: ``cache_epochs.json`` (``{model: epoch}``) and ``judge_drift.json``
(``{model, agreement, epoch, ts}`` plus ``changed``, ``threshold``, ``a0``; written by T5.4's
nightly
step; ``epoch`` is the cache epoch after the bump).
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import ConfigError

EPOCHS_FILE = "cache_epochs.json"
DRIFT_FILE = "judge_drift.json"
_MAX_BYTES = 1_000_000


class DriftFlag(BaseModel):
    """Content of ``judge_drift.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    agreement: float
    epoch: int
    ts: str
    changed: int | None = None  # T5.4 (D253): anchors whose raw score differs from the stored one
    threshold: int | None = None  # T5.4 (D308): the threshold the decision used
    a0: float | None = None  # T5.4 (D253): self-agreement, recorded only


def drift_file(cache_dir: Path) -> Path:
    """Return the path of ``judge_drift.json`` inside ``cache_dir``."""
    return cache_dir / DRIFT_FILE


def _read_json(path: Path) -> object:
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as err:
        msg = f"{path.name}: cannot be read ({type(err).__name__})"
        raise ConfigError(msg) from err
    if len(raw) > _MAX_BYTES:
        msg = f"{path.name}: larger than {_MAX_BYTES} bytes"
        raise ConfigError(msg)
    try:
        return json.loads(raw)
    except ValueError as err:
        msg = f"{path.name}: not valid JSON"
        raise ConfigError(msg) from err


def _epochs(cache_dir: Path) -> dict[str, int]:
    data = _read_json(cache_dir / EPOCHS_FILE)
    if data is None:
        return {}
    ok = isinstance(data, dict) and all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
        for k, v in data.items()
    )
    if not ok or not isinstance(data, dict):
        msg = f"{EPOCHS_FILE}: expected an object of model -> non-negative integer"
        raise ConfigError(msg)
    return {str(k): int(v) for k, v in data.items()}


def current_epoch(cache_dir: Path, model: str) -> int:
    """Return the cache epoch of ``model`` (0 when ``cache_epochs.json`` is missing or silent).

    Raises:
        ConfigError: The file exists but is not ``{model: non-negative int}``.

    Examples:
        >>> import tempfile, pathlib
        >>> current_epoch(pathlib.Path(tempfile.mkdtemp()), "github/x")
        0
    """
    return _epochs(cache_dir).get(model, 0)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def invalidate_judge(cache_dir: Path, model: str) -> int:
    """Bump the cache epoch of ``model``; every verdict cached before now misses.

    Args:
        cache_dir: Directory of ``cache_epochs.json`` (created when missing).
        model: Judge model id.

    Returns:
        The new epoch.

    Raises:
        ConfigError: ``cache_epochs.json`` is corrupt.
    """
    epochs = _epochs(cache_dir)
    epochs[model] = epochs.get(model, 0) + 1
    _write_atomic(cache_dir / EPOCHS_FILE, json.dumps(epochs, sort_keys=True))
    return epochs[model]


def read_drift(cache_dir: Path) -> DriftFlag | None:
    """Return the drift flag, or None when ``judge_drift.json`` does not exist.

    Raises:
        ConfigError: The file exists but is not a valid flag.
    """
    data = _read_json(drift_file(cache_dir))
    if data is None:
        return None
    try:
        return DriftFlag.model_validate(data)
    except ValidationError as err:
        msg = f"{DRIFT_FILE}: invalid ({err.error_count()} problem(s))"
        raise ConfigError(msg) from err


def clear_drift(cache_dir: Path, model: str) -> None:
    """Remove the drift flag when it names ``model``; the bumped cache epoch stays."""
    flag = read_drift(cache_dir)
    if flag is not None and flag.model == model:
        drift_file(cache_dir).unlink(missing_ok=True)
