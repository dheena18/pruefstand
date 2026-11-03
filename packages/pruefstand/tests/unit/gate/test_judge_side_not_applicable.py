"""Judge-side ``not_applicable`` values: excluded but capped like judge errors (B1, B1')."""

import pytest
from testsupport.builders import NA, make_case, make_run
from testsupport.gate_helpers import FAIL, PASS, gate

from pruefstand.core.models.metric import JUDGE_SIDE_REASONS
from pruefstand.gate.tables import PairedTable, pair_runs

M = "faithfulness"


def reasons(indices: range, reason: str) -> dict[str, dict[int, dict[str, str]]]:
    return {M: {i: {"reason": reason} for i in indices}}


def run_pair(reason: str | None) -> PairedTable:
    cases = [make_case(i, cluster=i) for i in range(4)]
    base = make_run("base", cases, {M: [1.0] * 4, "error_rate": [0.0] * 4})
    details = {} if reason is None else {M: {0: {"reason": reason}}}
    cand = make_run(
        "cand", cases, {M: [NA, 1.0, 1.0, 1.0], "error_rate": [0.0] * 4}, details=details
    )
    return pair_runs(base, cand, M, higher_is_better=True)


@pytest.mark.parametrize("reason", sorted(JUDGE_SIDE_REASONS))
def test_a_judge_side_reason_is_flagged_like_a_judge_error(reason: str) -> None:
    table = run_pair(reason)
    assert bool(table.judge_error[0]) is True  # the gate caps its exclusion at 20 %


@pytest.mark.parametrize("reason", [None, "missing_chunks", "base_answer_missing", "hard_fail"])
def test_a_real_not_applicable_of_the_candidate_is_worst_filled(reason: str | None) -> None:
    table = run_pair(reason)
    assert table.n_worst_filled == 1
    assert not table.judge_error.any()
    assert float(table.diffs.min()) == -1.0


def test_input_too_long_is_candidate_side_and_worst_filled() -> None:
    table = run_pair("judge_input_too_long")
    assert not table.judge_error.any()
    assert float(table.diffs.min()) == -1.0


# --- the reviewer's probes against the real evaluate_gate (60 clusters, baseline 0.9) -------


def test_probe_a_25_answers_too_long_for_the_judge_fail_the_gate() -> None:
    report = gate(
        {M: dict.fromkeys(range(25), NA)}, details=reasons(range(25), "judge_input_too_long")
    )
    assert report.status is FAIL


def test_probe_a_25_judge_side_excluded_cases_are_over_the_cap_and_fail() -> None:
    report = gate({M: dict.fromkeys(range(25), NA)}, details=reasons(range(25), "canary_in_input"))
    assert report.status is FAIL


def test_a_few_judge_side_excluded_cases_stay_excluded() -> None:
    report = gate({M: dict.fromkeys(range(5), NA)}, details=reasons(range(5), "canary_in_input"))
    assert report.status is PASS
    assert report.n_excluded[M] == 5
    assert report.not_applicable_counts[M] == 5
    assert report.not_applicable_counts[f"{M}: canary_in_input"] == 5  # per-reason breakdown


def test_probe_b_most_cases_excluded_and_the_rest_bad_cannot_pass() -> None:
    edits = {M: {i: (NA if i < 85 else 0.0) for i in range(120)}}
    report = gate(edits, details=reasons(range(85), "judge_cap"))
    assert report.status is FAIL
    assert all(d.informational_reason is None for d in report.decisions if d.metric == M)


def test_probe_b_with_half_excluded_still_fails() -> None:
    edits = {M: {i: (NA if i < 60 else 0.0) for i in range(120)}}
    assert gate(edits, details=reasons(range(60), "judge_quota")).status is FAIL


def test_a_real_not_applicable_keeps_its_meaning_in_the_gate() -> None:
    edits = {M: dict.fromkeys(range(25), NA)}
    assert gate(edits, details=reasons(range(25), "missing_chunks")).status is FAIL
