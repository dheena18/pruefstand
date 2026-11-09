"""T5.3 / round 13 AI13-12: seeded cluster-level dev/test split, stratified by label and hard_type.

The split is checked on the committed v1 sets (real items) and on the fixture builders.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from rq2.calib_quad import build_correctness, sample_questions
from rq2.calib_schema import CalibrationItem
from rq2.calib_sources import load_germanquad
from rq2.calib_split import assign_calib_split, stratum

REPO = Path(__file__).resolve().parents[3]
V1 = REPO / "datasets/calibration/v1"
FIXTURES = Path(__file__).parent / "fixtures"
SETS = ("faithfulness_constructed", "correctness", "refusal", "consistency")


def _load(name: str) -> list[CalibrationItem]:
    lines = (V1 / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [CalibrationItem.model_validate_json(line) for line in lines]


def _unsplit(items: list[CalibrationItem]) -> list[CalibrationItem]:
    return [it.model_copy(update={"calib_split": None}) for it in items]


@pytest.mark.parametrize("name", SETS)
def test_committed_split_is_reproducible_and_cluster_pure(name: str) -> None:
    items = _load(name)
    assert all(it.calib_split in {"dev", "test"} for it in items)
    assert assign_calib_split(_unsplit(items), seed=1234) == items
    splits: dict[str, set[str]] = defaultdict(set)
    for it in items:
        splits[it.cluster_id].add(str(it.calib_split))
    assert all(len(s) == 1 for s in splits.values())


@pytest.mark.parametrize("name", SETS)
def test_dev_share_per_set_label_and_hard_type(name: str) -> None:
    items = _load(name)
    dev = sum(it.calib_split == "dev" for it in items) / len(items)
    assert abs(dev - 0.30) <= 0.05
    total: Counter[tuple[int, str]] = Counter(stratum(it) for it in items)
    dev_n: Counter[tuple[int, str]] = Counter(
        stratum(it) for it in items if it.calib_split == "dev"
    )
    for key, n in total.items():
        if n >= 40:  # tiny strata cannot hit ±0.05 with whole clusters
            assert abs(dev_n[key] / n - 0.30) <= 0.05, (key, dev_n[key], n)


def test_stats_report_dev_and_test_counts() -> None:
    stats = json.loads((V1 / "stats.json").read_text(encoding="utf-8"))
    for name in (*SETS, "faithfulness_memerag"):
        entry = stats["sets"][name]
        assert set(entry["calib_split"]) == {"dev", "test"}
        assert sum(entry["calib_split"].values()) == entry["n_items"]
    for metric in ("faithfulness", "answer_correctness"):
        assert stats["hard_negatives_per_metric"][metric]["all"] >= 150
        assert stats["hard_negatives_per_metric"][metric]["test"] >= 105


def test_fixture_split_twice_identical() -> None:
    quad = load_germanquad(FIXTURES / "germanquad_test_6.jsonl")
    items = build_correctness(sample_questions(quad, 1234), quad, 1234)
    first, second = assign_calib_split(items, 1234), assign_calib_split(items, 1234)
    assert first == second
    assert {it.calib_split for it in first} <= {"dev", "test"}
