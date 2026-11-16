"""T5.4 S3: degraded pairs are deterministic, really changed, and built from top-label answers
only."""

import re
from pathlib import Path

import pytest
from rq2.make_degraded import OUT, discrimination, load_pairs, make_pairs
from rq2.rq2_config import REPO, load_config, load_items

from pruefstand.core.errors import ConfigError

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")


def test_same_seed_gives_the_same_pairs_and_only_label_two_answers() -> None:
    items = load_items(CFG.set_named("correctness"), "test")
    first = make_pairs(items, "correctness", seed=1234)
    assert first == make_pairs(items, "correctness", seed=1234)
    swaps = [p for p in first if p["edit"] == "swap_first_number"]
    assert len(swaps) == 50
    labels = {i.item_id: i.label for i in items}
    for pair in first:
        assert labels[str(pair["base_item_id"])] == 2
        assert pair["degraded"] != pair["inputs"]


def test_discrimination_counts_strictly_lower_scores() -> None:
    assert discrimination([(2, 1), (2, 2)]) == 0.5


def test_the_pair_files_are_split_by_licence() -> None:
    assert OUT["correctness"].name.endswith("germanquad.jsonl")
    assert OUT["faithfulness_constructed"].name.endswith("germanrag.jsonl")
    sets = {str(p["label_set"]) for p in load_pairs()}
    assert sets <= {"correctness", "faithfulness_constructed"}
    for name, path in OUT.items():
        if (REPO / path).is_file():
            rows = (REPO / path).read_text(encoding="utf-8").splitlines()
            assert all(f'"label_set": "{name}"' in r for r in rows)  # never mixed (D864)


def test_a_missing_pair_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_pairs(tmp_path)


def test_the_committed_correctness_negate_cell_has_42_pairs() -> None:
    pairs = [p for p in load_pairs() if p["label_set"] == "correctness"]
    negates = [p for p in pairs if p["edit"] == "negate"]
    assert len(negates) == 42
    forms = [p["form"] for p in negates]
    assert forms.count("span") == 21  # the T5.4 pairs, unchanged (D932)
    assert forms.count("sentence") == 21  # T5.4b2 (D1300): single-sentence bases only
    labels = {i.item_id: i.label for i in load_items(CFG.set_named("correctness"), "test")}
    for pair in negates:
        assert labels[str(pair["base_item_id"])] == 2  # test-split positives only
        base, worse = pair["inputs"], pair["degraded"]
        assert isinstance(base, dict)
        assert isinstance(worse, dict)
        assert base["referenz"] == worse["referenz"]
        assert base["antwort"] != worse["antwort"]
        assert re.search(r"nicht|[Kk]ein", worse["antwort"] + " " + base["antwort"])
