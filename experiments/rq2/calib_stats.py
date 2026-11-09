"""Per-set statistics and JSON-lines output of the calibration sets (T5.3 S4)."""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rq2.calib_schema import CalibrationItem
from rq2.calib_split import positive_share


def set_stats(items: Sequence[CalibrationItem], license_config: str) -> dict[str, Any]:
    """Return the ``stats.json`` entry of one label set.

    Args:
        items: The set's items, with ``calib_split`` assigned.
        license_config: HF config of the set (``none`` for MEMERAG, which is never published).

    Returns:
        Counts, label balance, trivial share, clusters, hard negatives per ``hard_type`` (all and
        ``test``), dev/test counts and constructions.
    """
    hard = [it for it in items if it.hard_negative]
    return {
        "metric": items[0].metric if items else None,
        "license_config": license_config,
        "n_items": len(items),
        "labels": {str(k): v for k, v in sorted(Counter(it.label for it in items).items())},
        "positive_share": round(positive_share(items), 4),
        "trivial_share": round(sum(it.trivial for it in items) / len(items), 4) if items else 0.0,
        "n_clusters": len({it.cluster_id for it in items}),
        "calib_split": dict(sorted(Counter(str(it.calib_split) for it in items).items())),
        "hard_negatives": len(hard),
        "hard_types": dict(sorted(Counter(str(it.hard_type) for it in hard).items())),
        "hard_types_test": dict(
            sorted(Counter(str(it.hard_type) for it in hard if it.calib_split == "test").items())
        ),
        "constructions": dict(sorted(Counter(it.construction for it in items).items())),
    }


def hard_negatives_per_metric(stats: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Sum hard negatives (all and ``test``) per metric over the sets in ``stats``."""
    out: dict[str, dict[str, int]] = {}
    for entry in stats.values():
        agg = out.setdefault(str(entry["metric"]), {"all": 0, "test": 0})
        agg["all"] += int(entry["hard_negatives"])
        agg["test"] += sum(int(v) for v in entry["hard_types_test"].values())
    return out


def write_jsonl(items: Sequence[CalibrationItem], path: Path) -> None:
    """Write ``items`` as compact UTF-8 JSON lines (keys in schema order, defaults left out).

    Defaults (``trivial=False``, ``hard_negative=False``, ``hard_type=None``) are omitted so the
    largest set stays under the 1 MB limit of ``scripts/check_no_raw_data.py`` (D866); loading
    with ``CalibrationItem.model_validate_json`` restores them.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        json.dumps(it.model_dump(exclude_defaults=True), ensure_ascii=False, separators=(",", ":"))
        for it in items
    )
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
