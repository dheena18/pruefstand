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
