"""T5.4 S7: the calibration table never pools label sets and labels every row's origin."""

import polars as pl
from rq2.report_tables import label_frame
from rq2.rq2_config import REPO, load_config, load_items

from pruefstand.judges.calibration import calibration_table

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")


def test_rows_are_per_label_set_and_carry_their_origin() -> None:
    items = []
    for name in ("faithfulness_constructed", "correctness"):
        entry = CFG.set_named(name)
        items += [(name, entry.origin, i) for i in load_items(entry, "test")[:40]]
    labels = label_frame(items)
    # the gold label as the "judge" score: a perfect rater, so only the grouping is under test
    verdicts = labels.select("item_id", "metric", pl.col("label").alias("score")).with_columns(
        pl.lit("ollama/gemma3:12b").alias("judge")
    )
    table = calibration_table(labels, verdicts)
    assert set(table["label_set"].to_list()) == {"faithfulness_constructed", "correctness"}
    assert table["label_origin"].null_count() == 0
    full = table.filter(pl.col("stratum") == "all")
    assert full.height == 2
    assert full["n"].sum() == 80
