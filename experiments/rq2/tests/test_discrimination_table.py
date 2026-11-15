"""T5.4b: discrimination per edit with its Wilson interval, and the span/sentence breakdown."""

import polars as pl
import pytest
from rq2.report_tables import discrimination_table

from pruefstand.judges.calibration import wilson_interval


def _pairs() -> pl.DataFrame:
    # 21 span pairs (13 lower) + 29 sentence pairs (28 lower) of one negate cell, 1 failed call
    cells: list[tuple[str, int, int | None, int]] = [
        ("span", 2, 0, 13),
        ("span", 2, 2, 8),
        ("sentence", 2, 0, 28),
        ("sentence", 1, 1, 1),
        ("sentence", 2, None, 1),
    ]
    rows = [(form, base, worse) for form, base, worse, k in cells for _ in range(k)]
    return pl.DataFrame(
        {
            "judge": ["ollama/gemma3:12b"] * len(rows),
            "label_set": ["correctness"] * len(rows),
            "metric": ["answer_correctness"] * len(rows),
            "edit": ["negate"] * len(rows),
            "form": [r[0] for r in rows],
            "base": [r[1] for r in rows],
            "degraded": [r[2] for r in rows],
        }
    )


def test_one_row_per_edit_with_a_wilson_interval() -> None:
    table = discrimination_table(_pairs())
    assert table.height == 1
    row = table.row(0, named=True)
    assert row["n"] == 50  # the failed call is left out
    assert row["discrimination"] == pytest.approx(41 / 50)
    low, high = wilson_interval(41, 50)
    assert row["discrimination_ci_low"] == pytest.approx(low)
    assert row["discrimination_ci_high"] == pytest.approx(high)
    assert row["discrimination_ci_low"] < 0.82 < row["discrimination_ci_high"]


def test_the_form_breakdown_splits_the_cell() -> None:
    table = discrimination_table(_pairs(), ("form",))
    by_form = {r["form"]: r for r in table.iter_rows(named=True)}
    assert by_form["span"]["n"] == 21
    assert by_form["span"]["discrimination"] == pytest.approx(13 / 21)
    assert by_form["sentence"]["n"] == 29
    assert by_form["sentence"]["discrimination"] == pytest.approx(28 / 29)
    assert by_form["sentence"]["base_top_share"] == pytest.approx(28 / 29)
