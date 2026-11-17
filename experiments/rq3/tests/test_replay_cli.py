"""T7.2 S3b: the replay CLI reads T6.3's sigma_d, uses the mean-zero pairs and writes replay.csv."""

import csv
from pathlib import Path

import numpy as np
import pytest
from noise.replay import aa_pair
from rq3.replay import replay_arm
from rq3.replay_cli import COLUMNS, load_sigma, prereg_sha, write_rows
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import DIRECTIONS, POLICY

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunResults

MDE_CSV = """metric,slice,sigma_d_noop,sigma_d_churn
context_recall,overall,0.05,0.12
context_recall,tenant=a,0.07,0.15
faithfulness,overall,0.04,0.10
"""


def test_load_sigma_reads_the_overall_rows_of_the_arm(tmp_path: Path) -> None:
    path = tmp_path / "mde.csv"
    path.write_text(MDE_CSV, encoding="utf-8")
    assert load_sigma(path, "noop") == {"context_recall": 0.05, "faithfulness": 0.04}
    assert load_sigma(path, "churn") == {"context_recall": 0.12, "faithfulness": 0.10}


def test_load_sigma_refuses_a_file_without_the_arm(tmp_path: Path) -> None:
    path = tmp_path / "mde.csv"
    path.write_text("metric,slice,sigma_d\ncontext_recall,overall,0.1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sigma_d_noop"):
        load_sigma(path, "noop")


def test_the_real_pairs_rarely_alarm_and_the_rows_are_written(tmp_path: Path) -> None:
    cases, values = fixture_f0()
    baseline: RunResults = make_run("base", cases, values)
    sigma = {"context_recall": 0.12, "faithfulness": 0.10}

    def pairs(rng: np.random.Generator) -> tuple[RunResults, RunResults]:
        return aa_pair(baseline, sigma, rng)

    results = replay_arm(pairs, POLICY, directions=DIRECTIONS, n=3, seed=1234)
    assert all(r.fail == 0 for r in results)  # mean-zero A/A pairs at a realistic sigma_d
    out = tmp_path / "rq3" / "replay.csv"
    write_rows(out, "abc123", "churn", results)
    write_rows(out, "abc123", "noop", results)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(rows[0]) == COLUMNS
    assert [(r["arm"], r["variant"]) for r in rows] == [
        ("churn", "pruefstand"), ("churn", "naive"), ("churn", "no_slices"),
        ("noop", "pruefstand"), ("noop", "naive"), ("noop", "no_slices"),
    ]  # fmt: skip
    assert {r["prereg_sha"] for r in rows} == {"abc123"}


def test_the_prereg_sha_is_a_commit() -> None:
    sha = prereg_sha()
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)
