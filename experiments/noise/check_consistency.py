"""T6.3 S3: the shipped gate thresholds equal the SPEC defaults (or a decision records why not).

δ (``max_drop``) is a product decision (SPEC §7.2): this check compares ``pruefstand.yaml`` with
the ``gate:`` block of ``docs/spec/SPEC.md`` §5.6 key by key, so a threshold is never changed
silently.

Usage::

uv run python experiments/noise/check_consistency.py # exit 1 and one line per difference
"""

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
GATE_KEYS = (
    "hard_fail",
    "gated_slices",
    "min_clusters",
    "n_resamples",
    "correction",
    "alpha",
    "warn_p",
)
RULE_KEYS = ("max_drop", "max_value")
# "gate.<key>" or "gate.metrics.<metric>.<rule>" -> decision id that records an intended difference.
RECORDED: Mapping[str, str] = {}
_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.S)


def spec_gate(spec_text: str) -> dict[str, Any]:
    """Return the ``gate`` mapping of the first YAML block of the SPEC that has one.

    Raises:
        ValueError: no YAML block of the SPEC has a ``gate`` mapping.
    """
    for block in _YAML_BLOCK.findall(spec_text):
        data = yaml.safe_load(block)
        gate = data.get("gate") if isinstance(data, dict) else None
        if isinstance(gate, dict):
            return {str(k): v for k, v in gate.items()}
    msg = "no YAML block with a gate mapping in the SPEC"
    raise ValueError(msg)


def differences(
    shipped: Mapping[str, Any], spec: Mapping[str, Any], recorded: Mapping[str, str] = RECORDED
) -> list[str]:
    """Compare two ``gate`` mappings; return one line per unrecorded difference.

    Examples:
        >>> differences({"alpha": 0.025, "metrics": {}}, {"alpha": 0.05, "metrics": {}})
        ['gate.alpha: shipped 0.025, SPEC 0.05']
    """
    found = []
    for key in GATE_KEYS:
        if shipped.get(key) != spec.get(key):
            found.append((f"gate.{key}", shipped.get(key), spec.get(key)))
    metrics = sorted(set(shipped.get("metrics", {})) | set(spec.get("metrics", {})))
    for metric in metrics:
        ours, theirs = shipped["metrics"].get(metric) or {}, spec["metrics"].get(metric) or {}
        for rule in RULE_KEYS:
            if ours.get(rule) != theirs.get(rule):
                found.append((f"gate.metrics.{metric}.{rule}", ours.get(rule), theirs.get(rule)))
    return [f"{key}: shipped {a}, SPEC {b}" for key, a, b in found if key not in recorded]


def main(argv: list[str] | None = None) -> int:
    """Check ``pruefstand.yaml`` against the SPEC; print each difference; exit 1 if any."""
    del argv
    shipped = yaml.safe_load((REPO / "pruefstand.yaml").read_text(encoding="utf-8"))["gate"]
    spec = spec_gate((REPO / "docs/spec/SPEC.md").read_text(encoding="utf-8"))
    problems = differences(shipped, spec)
    for line in problems:
        print(line)
    if not problems:
        print("gate thresholds match the SPEC defaults")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
