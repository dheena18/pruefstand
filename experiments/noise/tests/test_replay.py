"""T6.3 S2b (core): A/A replay through evaluate_gate on the gate's fixture F0."""

import numpy as np
from noise.replay import noop_candidate, replay
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import DIRECTIONS, POLICY

from pruefstand.core.models.run import RunResults


def baseline() -> RunResults:
    cases, values = fixture_f0()
    return make_run("base", cases, values)


def test_zero_sigma_never_alarms() -> None:
    result = replay(baseline(), {"context_recall": 0.0}, POLICY, directions=DIRECTIONS, n=5, seed=1)
    assert (result.n, result.fail, result.warn_or_fail) == (5, 0, 0)
    assert result.fail_ci[0] == 0.0 < result.fail_ci[1]


def test_a_huge_sigma_alarms_and_the_seed_fixes_the_counts() -> None:
    sigma = {"context_recall": 0.4, "faithfulness": 0.4}
    first = replay(baseline(), sigma, POLICY, directions=DIRECTIONS, n=3, seed=7)
    assert first.warn_or_fail > 0
    assert first == replay(baseline(), sigma, POLICY, directions=DIRECTIONS, n=3, seed=7)


def test_the_shift_is_one_draw_per_cluster_and_stays_in_the_unit_interval() -> None:
    base = baseline()
    cand = noop_candidate(base, {"context_recall": 0.3}, np.random.default_rng(2))
    moved: dict[str, set[float]] = {}
    for b, c in zip(base.values, cand.values, strict=True):
        before = {v.metric: v.value for v in b.values}
        for v in c.values:
            old = before[v.metric]
            if v.metric == "context_recall" and v.value is not None and old is not None:
                assert 0.0 <= v.value <= 1.0
                moved.setdefault(c.case.cluster_id, set()).add(round(v.value - old, 9))
            elif v.metric != "context_recall":
                assert v.value == before[v.metric]
    assert all(
        len(shifts) == 1 for shifts in moved.values()
    )  # both cases of a cluster move together
