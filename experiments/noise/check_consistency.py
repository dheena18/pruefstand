"""T6.3 S3: the shipped gate thresholds equal the SPEC defaults (or a decision records why not).

delta (``max_drop``) is a product decision (SPEC §7.2): this check compares the ``gate`` block of
``pruefstand.yaml`` with the ``gate:`` block of ``docs/spec/SPEC.md`` §5.6 over the **union** of
their keys, at the gate level and per metric rule, so no threshold or setting changes silently.

Usage::

    uv run python experiments/noise/check_consistency.py      # exit 1 and one line per difference
"""

import re
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
# "gate.<key>" or "gate.metrics.<metric>.<rule>" -> decision id that records an intended difference.
RECORDED: Mapping[str, str] = {}
_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.S)
Gate = Mapping[str, object]


def spec_gate(spec_text: str) -> dict[str, object]:
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


def _rules(gate: Gate) -> dict[str, dict[str, object]]:
    metrics = gate.get("metrics")
    if not isinstance(metrics, dict):
        return {}
    return {str(m): dict(r) if isinstance(r, dict) else {} for m, r in metrics.items()}


def differences(shipped: Gate, spec: Gate, recorded: Mapping[str, str] = RECORDED) -> list[str]:
    """Compare two ``gate`` mappings over the union of keys; one line per unrecorded difference.

    Examples:
        >>> differences({"alpha": 0.025}, {"alpha": 0.05})
        ['gate.alpha: shipped 0.025, SPEC 0.05']
        >>> differences({"new_key": 1}, {})
        ['gate.new_key: shipped 1, SPEC None']
    """
    found: list[tuple[str, object, object]] = []
    for key in sorted((set(shipped) | set(spec)) - {"metrics"}):
        if shipped.get(key) != spec.get(key):
            found.append((f"gate.{key}", shipped.get(key), spec.get(key)))
    ours, theirs = _rules(shipped), _rules(spec)
    for metric in sorted(set(ours) | set(theirs)):
        a, b = ours.get(metric, {}), theirs.get(metric, {})
        for rule in sorted(set(a) | set(b)):
            if a.get(rule) != b.get(rule):
                found.append((f"gate.metrics.{metric}.{rule}", a.get(rule), b.get(rule)))
    return [f"{key}: shipped {x}, SPEC {y}" for key, x, y in found if key not in recorded]


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
