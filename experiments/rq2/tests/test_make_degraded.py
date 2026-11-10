"""T5.4 S3: degraded pairs are deterministic, really changed, and built from top-label answers
only."""

from rq2.make_degraded import discrimination, make_pairs
from rq2.rq2_config import REPO, load_config, load_items

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
