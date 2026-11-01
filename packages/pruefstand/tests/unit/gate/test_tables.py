"""Pairing of two runs (``gate.tables``): ScoreTable per run, PairedTable, slice membership."""

import numpy as np
import pytest
from pruefstand.gate.slices import slice_members, slice_values
from testsupport.builders import NA, make_case, make_run

from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import ScoreTable
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.testcase import TestCase
from pruefstand.gate.tables import pair_runs, pair_tables, score_table

M = "context_recall"


def _cases() -> list[TestCase]:
    return [
        make_case(0, cluster=0, tenant="a", tags=("x", "y")),
        make_case(1, cluster=0, tenant="a"),
        make_case(2, cluster=1, tenant="b", lang="en", category="multi_hop"),
    ]


def _run(
    run_id: str,
    column: list[float | None],
    cases: list[TestCase] | None = None,
    **extra: list[float | None],
) -> RunResults:
    cs = cases if cases is not None else _cases()
    return make_run(run_id, cs, {M: column, "error_rate": [0.0] * len(cs), **extra})


def test_score_table_aligned_with_slices() -> None:
    table = score_table(_run("r", [0.5, 0.25, 1.0]), M, higher_is_better=True)
    assert isinstance(table, ScoreTable)
    assert table.case_ids == ("c0000", "c0001", "c0002")
    assert table.cluster_ids == ("k000", "k000", "k001")
    assert table.values == (0.5, 0.25, 1.0)
    assert table.higher_is_better is True
    assert table.slices["tenant"] == ("a", "a", "b")
    assert table.slices["lang"] == ("de", "de", "en")
    assert table.slices["category"] == ("factual", "factual", "multi_hop")
    assert table.slices["perturbation"] == ("", "", "")
    assert table.slices["tags"] == ("x|y", "", "")


def test_score_table_skips_non_ok_values() -> None:
    table = score_table(_run("r", [0.5, None, NA]), M, higher_is_better=True)
    assert table.case_ids == ("c0000",)


def test_pair_runs_equals_pairing_hand_built_tables() -> None:
    base, cand = _run("b", [0.5, 0.25, 1.0]), _run("c", [0.25, 0.25, 0.5])
    by_hand = pair_tables(
        score_table(base, M, higher_is_better=True), score_table(cand, M, higher_is_better=True)
    )
    paired = pair_runs(base, cand, M, higher_is_better=True)
    assert paired.case_ids == by_hand.case_ids == ("c0000", "c0001", "c0002")
    assert paired.cluster_ids.tolist() == by_hand.cluster_ids.tolist() == ["k000", "k000", "k001"]
    assert paired.diffs.tolist() == by_hand.diffs.tolist() == [-0.25, 0.0, -0.5]
    assert paired.base_values.tolist() == [0.5, 0.25, 1.0]
    assert paired.cand_values.tolist() == [0.25, 0.25, 0.5]
    assert (paired.n_unmatched, paired.n_excluded, paired.n_worst_filled) == (0, 0, 0)
    assert paired.attrs == by_hand.attrs


def test_cases_in_one_run_only_are_unmatched() -> None:
    cases = _cases()
    base = _run("b", [0.5, 0.25, 1.0])
    cand = _run("c", [0.5, 0.25], cases[:2])
    paired = pair_runs(base, cand, M, higher_is_better=True)
    assert paired.case_ids == ("c0000", "c0001")
    assert paired.n_unmatched == 1
    assert paired.n_excluded == 0


def test_baseline_not_applicable_is_excluded() -> None:
    paired = pair_runs(
        _run("b", [0.5, NA, 1.0]), _run("c", [0.5, 0.5, 1.0]), M, higher_is_better=True
    )
    assert paired.case_ids == ("c0000", "c0002")
    assert paired.n_excluded == 1
    assert paired.n_worst_filled == 0


def test_candidate_not_applicable_is_worst_filled() -> None:
    paired = pair_runs(
        _run("b", [0.5, 0.5, 1.0]), _run("c", [0.5, NA, 1.0]), M, higher_is_better=True
    )
    assert paired.cand_values.tolist() == [0.5, 0.0, 1.0]
    assert paired.diffs.tolist() == [0.0, -0.5, 0.0]
    assert paired.n_worst_filled == 1


def test_worst_value_is_one_for_lower_is_better() -> None:
    paired = pair_runs(
        _run("b", [0.5, 0.5, 1.0]), _run("c", [0.5, NA, 1.0]), M, higher_is_better=False
    )
    assert paired.cand_values.tolist() == [0.5, 1.0, 1.0]
    assert paired.diffs.tolist() == [-0.0, -0.5, -0.0]  # oriented: negative = worse


def test_judge_error_on_a_successful_request_is_flagged_not_counted_as_filled() -> None:
    paired = pair_runs(
        _run("b", [0.5, 0.5, 1.0]), _run("c", [0.5, None, 1.0]), M, higher_is_better=True
    )
    assert paired.case_ids == ("c0000", "c0001", "c0002")
    assert paired.judge_error.tolist() == [False, True, False]
    assert paired.diffs.tolist() == [0.0, -0.5, 0.0]  # the worst value, if the caller fills
    assert (paired.n_excluded, paired.n_worst_filled) == (0, 0)


def test_error_on_a_failed_request_is_worst_filled() -> None:
    cand = make_run("c", _cases(), {M: [0.5, None, 1.0], "error_rate": [0.0, 1.0, 0.0]})
    paired = pair_runs(_run("b", [0.5, 0.5, 1.0]), cand, M, higher_is_better=True)
    assert paired.case_ids == ("c0000", "c0001", "c0002")
    assert paired.diffs.tolist() == [0.0, -0.5, 0.0]
    assert paired.n_worst_filled == 1


def test_alignment_by_case_id_not_by_position() -> None:
    cases = _cases()
    base = _run("b", [0.5, 0.25, 1.0])
    cand = _run("c", [0.5, 0.5, 0.25], cases[::-1])  # c0002=0.5 c0001=0.5 c0000=0.25
    paired = pair_runs(base, cand, M, higher_is_better=True)
    assert paired.case_ids == ("c0000", "c0001", "c0002")
    assert paired.diffs.tolist() == [-0.25, 0.25, -0.5]


def test_direction_false_negates_the_differences() -> None:
    base, cand = _run("b", [0.5, 0.5, 0.5]), _run("c", [0.75, 0.5, 0.25])
    paired = pair_runs(base, cand, M, higher_is_better=False)
    assert paired.diffs.tolist() == [-0.25, 0.0, 0.25]
    assert paired.cand_values.tolist() == [0.75, 0.5, 0.25]  # raw values stay unoriented


def test_slice_membership_keeps_perturbed_cases_out_of_overall() -> None:
    cases = [
        make_case(0, cluster=0, tags=("t",)),
        make_case(1, cluster=0, perturbation="typos", base=0, tags=("t",)),
        make_case(2, cluster=1, perturbation="compound_split", base=2),
        make_case(3, cluster=1, tenant="b"),
    ]
    run = make_run("r", cases, {M: [0.5] * 4})
    table = pair_runs(run, run, M, higher_is_better=True)
    assert slice_members(table, "overall", "overall").tolist() == [True, False, False, True]
    assert slice_members(table, "perturbed_all", "perturbed_all").tolist() == [
        False, True, True, False,
    ]  # fmt: skip
    assert slice_members(table, "tenant", "kanzlei_mueller").tolist() == [True, False, False, False]
    assert slice_members(table, "tenant", "b").tolist() == [False, False, False, True]
    assert slice_members(table, "perturbation", "typos").tolist() == [False, True, False, False]
    assert slice_members(table, "tags", "t").tolist() == [True, False, False, False]
    assert slice_values(table, "tenant") == ("b", "kanzlei_mueller")
    assert slice_values(table, "perturbation") == ("compound_split", "typos")
    assert slice_values(table, "tags") == ("t",)
    assert slice_values(table, "lang") == ("de",)


def test_unknown_dimension_raises() -> None:
    run = _run("r", [0.5, 0.5, 0.5])
    table = pair_runs(run, run, M, higher_is_better=True)
    with pytest.raises(GateInputError, match="dimension"):
        slice_members(table, "colour", "red")


def test_pair_tables_counts_filled_and_unmatched_arguments() -> None:
    base = score_table(_run("b", [0.5, 0.5, 1.0]), M, higher_is_better=True)
    cand = score_table(_run("c", [0.5, 0.5], _cases()[:2]), M, higher_is_better=True)
    paired = pair_tables(base, cand, filled=frozenset({"c0001"}), n_unmatched=2, n_shared=3)
    assert np.array_equal(paired.diffs, [0.0, 0.0])
    assert (paired.n_unmatched, paired.n_excluded, paired.n_worst_filled) == (2, 1, 1)
