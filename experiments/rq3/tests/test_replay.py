"""T7.2 S3b (runner core): three variants decide the same synthetic pairs; alarms are counted."""

import numpy as np
import pytest
from rq3 import replay
from rq3.replay import VARIANTS, alarm_counts, decide_all, replay_arm
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import DIRECTIONS
from testsupport.gate_helpers import POLICY as GATE_POLICY

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.run import RunResults

POLICY = GATE_POLICY.model_copy(update={"min_clusters": 10})  # F0 tenants have 20 clusters


def runs(edit: dict[int, float]) -> tuple[RunResults, RunResults]:
    cases, values = fixture_f0()
    cand = {m: list(v) for m, v in values.items()}
    for i, value in edit.items():
        cand["context_recall"][i] = value
    return make_run("base", cases, values), make_run("cand", cases, cand)


def identical(_: np.random.Generator) -> tuple[RunResults, RunResults]:
    return runs({})


def tenant_drop(_: np.random.Generator) -> tuple[RunResults, RunResults]:
    return runs(dict.fromkeys(range(80, 120), 0.68))  # one tenant -0.12, overall -0.04


def test_identical_pairs_never_alarm_in_any_variant() -> None:
    results = replay_arm(identical, POLICY, directions=DIRECTIONS, n=2, seed=1)
    assert [r.variant for r in results] == list(VARIANTS)
    assert all((r.n, r.fail, r.warn_or_fail) == (2, 0, 0) for r in results)
    assert all(r.fail_ci[0] == 0.0 < r.fail_ci[1] for r in results)


def test_variants_are_counted_apart_on_the_same_pair() -> None:
    results = {
        r.variant: r for r in replay_arm(tenant_drop, POLICY, directions=DIRECTIONS, n=2, seed=1)
    }
    assert results["pruefstand"].fail == 2  # the tenant slice is gated
    assert results["naive"].fail == 0  # overall -0.04 < max_drop
    assert results["no_slices"].fail == 0


def test_decide_all_uses_the_production_gate_for_variant_one() -> None:
    left, right = tenant_drop(np.random.default_rng(0))
    decided = decide_all(left, right, POLICY, np.random.default_rng(1), directions=DIRECTIONS)
    assert decided["pruefstand"] is GateStatus.FAIL
    assert decided["naive"] is GateStatus.PASS


def test_the_seed_fixes_the_counts() -> None:
    first = replay_arm(tenant_drop, POLICY, directions=DIRECTIONS, n=2, seed=4)
    assert first == replay_arm(tenant_drop, POLICY, directions=DIRECTIONS, n=2, seed=4)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (GateStatus.PASS, (0, 0)),
        (GateStatus.WARN, (0, 1)),
        (GateStatus.UNSUPPORTED_CONFIG, (0, 1)),
        (GateStatus.FAIL, (1, 1)),
        (GateStatus.INSUFFICIENT_DATA, (0, 0)),
    ],
)
def test_alarm_counts_follow_amendment_a1(status: GateStatus, expected: tuple[int, int]) -> None:
    assert alarm_counts(status) == expected


def test_replay_arm_counts_each_variant_as_in_a1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed statuses: WARN is never a FAIL, UNSUPPORTED is a WARN, INSUFFICIENT is neither."""
    fixed = {
        "pruefstand": GateStatus.UNSUPPORTED_CONFIG,
        "naive": GateStatus.WARN,
        "no_slices": GateStatus.INSUFFICIENT_DATA,
    }
    monkeypatch.setattr(replay, "decide_all", lambda *_a, **_k: dict(fixed))
    got = {r.variant: (r.fail, r.warn_or_fail) for r in replay_arm(
        identical, GATE_POLICY, directions=DIRECTIONS, n=4, seed=1
    )}  # fmt: skip
    assert got == {"pruefstand": (0, 4), "naive": (0, 4), "no_slices": (0, 0)}
