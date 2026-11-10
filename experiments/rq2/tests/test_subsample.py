"""T5.4 S2: the 300-item GitHub Models subsample is deterministic and stratified."""

import json
from collections import Counter
from pathlib import Path

from rq2.calib_schema import CalibrationItem
from rq2.subsample import stratified_subsample

REPO = Path(__file__).resolve().parents[3]


def _items(name: str) -> list[CalibrationItem]:
    path = REPO / "datasets/calibration/v1" / f"{name}.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    return [CalibrationItem.model_validate(json.loads(r)) for r in rows]


def _shares(items: list[CalibrationItem]) -> dict[tuple[int, str], float]:
    counts = Counter((i.label, i.hard_type or "") for i in items)
    return {k: v / len(items) for k, v in counts.items()}


def test_subsample_is_deterministic_and_stratified() -> None:
    for name in ("faithfulness_constructed", "correctness", "refusal"):
        items = _items(name)
        first = stratified_subsample(items, 300, seed=1234)
        assert [i.item_id for i in first] == [
            i.item_id for i in stratified_subsample(items, 300, 1234)
        ]
        assert len(first) == 300
        full, sub = _shares(items), _shares(first)
        for key, share in full.items():
            assert abs(sub.get(key, 0.0) - share) <= 0.02, (name, key)


def test_a_small_set_is_returned_whole() -> None:
    items = _items("correctness")[:10]
    assert stratified_subsample(items, 300) == items
