"""T5.4 S9: the 50 drift anchors (X3.4): seeded, half hard negatives, no MEMERAG, rendered
requests."""

import json
from collections import defaultdict
from pathlib import Path

import pytest
from rq2.anchors import anchor_rows, publishable_sets, screened_out, select_anchors
from rq2.calib_schema import is_positive
from rq2.flips import flip_summary
from rq2.rq2_config import REPO, load_config

from pruefstand.judges.anchors import AnchorItem, anchor_file, load_anchors

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


def test_the_stored_verdict_is_the_majority_and_flips_come_from_later_runs() -> None:
    # T5.4d (D1250): two unstable anchors that are 2 in run 1 and 1 in most later runs
    stable = [[2, 0, 1] for _ in range(9)]
    runs = [[*row, 2, 2] for row in stable]
    for k in range(1, 9):
        runs[k][3:] = [1, 1] if k != 6 else [1, 2]
    old = flip_summary(runs[:4], "m")  # T5.4: run 1 stored, runs 2-4 counted
    assert (old["flips"], old["comparisons"], old["majority_runs"]) == (6, 15, 1)
    new = flip_summary(runs, "m", majority_runs=5)
    assert new["stored"] == [2, 0, 1, 1, 1]
    assert (new["flips"], new["comparisons"]) == (1, 20)  # run 7, anchor 5
    assert new["a0"] == 1.0
    assert new["changed_anchors"] == 2
    kept = new["runs"]
    assert isinstance(kept, list)
    assert len(kept) == 9  # every run's scores are kept


def test_majority_runs_must_leave_runs_to_count() -> None:
    with pytest.raises(ValueError, match="majority_runs"):
        flip_summary([[1], [1]], "m", majority_runs=2)


def test_rows_record_the_runs_of_their_majority() -> None:
    picked = select_anchors(publishable_sets(CFG), 1234)[:2]
    rows = anchor_rows(picked, [2, 0], "ollama/gemma3:12b", majority_runs=5)
    assert [r.majority_runs for r in rows] == [5, 5]
    old = rows[0].model_dump(exclude={"majority_runs"})
    assert AnchorItem.model_validate(old).majority_runs == 1  # T5.4 files still load


def test_an_excluded_anchor_is_replaced_in_place_by_a_spare_of_its_stratum() -> None:
    sets = publishable_sets(CFG)
    base = select_anchors(sets, 1234)
    gone = base[3][1]
    swapped = select_anchors(sets, 1234, exclude=[gone.item_id])
    assert len(swapped) == 50
    changed = [k for k, (a, b) in enumerate(zip(base, swapped, strict=True)) if a != b]
    assert changed == [3]  # every other anchor stays
    new = swapped[3][1]
    assert new.item_id not in {i.item_id for _, i in base}
    assert (new.metric, new.hard_negative) == (gone.metric, gone.hard_negative)
    assert swapped == select_anchors(sets, 1234, exclude=[gone.item_id])  # seeded


def test_the_screen_must_belong_to_the_current_anchor_file(tmp_path: Path) -> None:
    rows = load_anchors(anchor_file("ollama/gemma3:12b"))
    good = tmp_path / "screen.json"
    runs = [[r.raw_score for r in rows] for _ in range(9)]
    runs[1][4] = runs[3][4] = runs[5][4] = 1 - min(runs[0][4], 1)  # anchor 4: 6 of 9 = unstable
    good.write_text(json.dumps({"stored": runs[0], "runs": runs}), encoding="utf-8")
    assert screened_out(good, "ollama/gemma3:12b") == [rows[4].item_id]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"stored": [9] * 50, "runs": runs}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        screened_out(bad, "ollama/gemma3:12b")
