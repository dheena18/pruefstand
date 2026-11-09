"""Promote-time check: a run whose errors the gate could not tolerate is no baseline (T1.7a)."""

import pytest
from testsupport.builders import make_case, make_run
from testsupport.gate_helpers import DIRECTIONS, POLICY

from pruefstand.core.errors import GateInputError
from pruefstand.core.models.run import RunResults
from pruefstand.gate.baseline_run import check_baseline_run


def _run(en_clusters: int, errors: int) -> RunResults:
    n = 300
    cases = [make_case(i, cluster=i, lang="en" if i < en_clusters else "de") for i in range(n)]
    faithfulness: list[float | None] = [0.9] * n
    for i in range(errors):
        faithfulness[i] = None
    return make_run("base", cases, {"faithfulness": faithfulness, "error_rate": [0.0] * n})


def test_two_errors_in_a_31_cluster_slice_are_refused() -> None:
    with pytest.raises(GateInputError, match=r"29 of 31 clusters of lang=en.*re-run"):
        check_baseline_run(_run(31, 2), POLICY, DIRECTIONS)


def test_a_clean_baseline_and_a_tolerable_one_pass() -> None:
    check_baseline_run(_run(31, 0), POLICY, DIRECTIONS)
    check_baseline_run(_run(60, 3), POLICY, DIRECTIONS)


def test_errors_beyond_the_cap_are_refused() -> None:
    with pytest.raises(GateInputError, match="baseline errors on 13 of 60"):
        check_baseline_run(_run(60, 13), POLICY, DIRECTIONS)


def _perturbed_run(metric: str) -> RunResults:
    """300 base cases plus 60 perturbed cases (own clusters); 15 of the perturbed ones errored."""
    base = [make_case(i, cluster=i) for i in range(300)]
    perturbed = [
        make_case(300 + i, cluster=300 + i, perturbation="typo", base=i) for i in range(60)
    ]
    column: list[float | None] = [0.9] * 360
    for i in range(300, 315):
        column[i] = None
    return make_run("base", [*base, *perturbed], {metric: column, "error_rate": [0.0] * 360})


def test_perturbed_all_is_checked_only_for_retrieval_metrics() -> None:
    """The gate builds no `perturbed_all` pair for faithfulness, so errors there are fine."""
    check_baseline_run(_perturbed_run("faithfulness"), POLICY, DIRECTIONS)
    with pytest.raises(GateInputError, match="perturbed_all"):
        check_baseline_run(_perturbed_run("context_recall"), POLICY, DIRECTIONS)


def test_skipped_metrics_are_not_checked() -> None:
    """Metrics the gate treats as informational (the caller's `skip`) cannot refuse a baseline."""
    with pytest.raises(GateInputError, match="baseline errors on 13 of 60"):
        check_baseline_run(_run(60, 13), POLICY, DIRECTIONS)
    check_baseline_run(_run(60, 13), POLICY, DIRECTIONS, skip={"faithfulness"})
