"""Judge-side ``not_applicable`` values are left out of the pairing, never worst-filled (B1)."""

import pytest
from testsupport.builders import NA, make_case, make_run

from pruefstand.core.models.metric import JUDGE_SIDE_REASONS
from pruefstand.gate.tables import pair_runs

M = "faithfulness"


def runs(reason: str | None) -> tuple[object, object]:
    cases = [make_case(i, cluster=i) for i in range(4)]
    base = make_run("base", cases, {M: [1.0] * 4, "error_rate": [0.0] * 4})
    details = {} if reason is None else {M: {0: {"reason": reason}}}
    cand = make_run(
        "cand", cases, {M: [NA, 1.0, 1.0, 1.0], "error_rate": [0.0] * 4}, details=details
    )
    return base, cand


@pytest.mark.parametrize("reason", sorted(JUDGE_SIDE_REASONS))
def test_a_judge_side_reason_is_excluded_not_filled(reason: str) -> None:
    base, cand = runs(reason)
    table = pair_runs(base, cand, M, higher_is_better=True)  # type: ignore[arg-type]
    assert table.n_worst_filled == 0
    assert table.n_excluded == 1
    assert len(table.case_ids) == 3
    assert float(table.diffs.min()) == 0.0  # no silent zero against the baseline's 1.0


@pytest.mark.parametrize("reason", [None, "missing_chunks", "base_answer_missing", "hard_fail"])
def test_a_real_not_applicable_of_the_candidate_keeps_its_meaning(reason: str | None) -> None:
    base, cand = runs(reason)
    table = pair_runs(base, cand, M, higher_is_better=True)  # type: ignore[arg-type]
    assert table.n_worst_filled == 1
    assert float(table.diffs.min()) == -1.0
