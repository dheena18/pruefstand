"""T5.4 S9: the 50 drift anchors (X3.4): seeded, half hard negatives, no MEMERAG, rendered
requests."""

from collections import defaultdict

import pytest
from rq2.anchors import anchor_rows, publishable_sets, select_anchors
from rq2.calib_schema import is_positive
from rq2.rq2_config import REPO, load_config

from pruefstand.judges.anchors import anchor_file, load_anchors

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")


def test_seed_gives_the_same_50_items_with_25_hard_negatives() -> None:
    sets = publishable_sets(CFG)
    first = select_anchors(sets, 1234)
    assert [i.item_id for _, i in first] == [i.item_id for _, i in select_anchors(sets, 1234)]
    assert len(first) == 50
    assert sum(1 for _, i in first if i.hard_negative) == 25
    assert all(i.source != "memerag" and "memerag" not in name for name, i in first)
    labels: dict[str, set[bool]] = defaultdict(set)
    for _, item in first:
        labels[item.metric].add(is_positive(item))
    assert all(v == {True, False} for v in labels.values())
    assert len(labels) == 4


def test_memerag_items_are_refused() -> None:
    sets = publishable_sets(CFG)
    sets["memerag"] = sets["faithfulness_constructed"]
    with pytest.raises(ValueError, match="MEMERAG"):
        select_anchors(sets, 1234)


def test_rows_hold_the_rendered_request_and_the_raw_verdict() -> None:
    picked = select_anchors(publishable_sets(CFG), 1234)[:3]
    rows = anchor_rows(picked, [2, 0, 1], "ollama/gemma3:12b")
    assert [r.raw_score for r in rows] == [2, 0, 1]
    for row, (_, item) in zip(rows, picked, strict=True):
        text = "\n".join(m.content for m in row.messages)
        assert item.inputs["antwort"][:20] in text
        assert row.request().json_schema is not None


def test_the_committed_anchor_file_has_50_valid_lines() -> None:
    path = anchor_file("ollama/gemma3:12b")
    if not path.is_file():
        pytest.skip("anchor file not recorded yet (experiments/rq2/anchors.py on the VM)")
    rows = load_anchors(path)
    assert len(rows) == 50
    assert sum(1 for r in rows if r.hard_negative) == 25
