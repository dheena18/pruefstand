"""RQ3 A/A replay arm (T7.2 S3b): the false-alarm rate of all three gate variants on the same pairs.

``PREREGISTRATION.md`` §5: at least 500 synthetic no-op pairs per variant, once with sigma_d(no-op)
(primary) and once with sigma_d(churn). Every pair is decided by the three variants of
``baselines.py`` (production ``evaluate_gate``, the naive mean gate, the no-slices gate), so only
the decision rule differs. Statuses are counted as pre-registered (amendment A1): FAIL is a false
block; FAIL, WARN and UNSUPPORTED_CONFIG are a false warn or worse; INSUFFICIENT_DATA is neither.

The pairs come from a factory: T6.3's mean-zero ``noise.replay.aa_pair`` with the measured sigma_d
in the real arm; the tests pass hand-built pairs.
"""

from collections.abc import Callable, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict
from rq3.baselines import naive_gate, no_slice_gate
from rq3.score import Variant, counted_status

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.run import RunResults
from pruefstand.gate.policy import evaluate_gate
from pruefstand.gate.stats import wilson_interval

PairFactory = Callable[[np.random.Generator], tuple[RunResults, RunResults]]
VARIANTS: tuple[Variant, ...] = ("pruefstand", "naive", "no_slices")
ALARM = frozenset({GateStatus.FAIL, GateStatus.WARN})


class ArmResult(BaseModel):
    """False-block (FAIL) and false-warn-or-worse counts of one variant, with Wilson 95 % CIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    variant: Variant
    n: int
    fail: int
    warn_or_fail: int
    fail_ci: tuple[float, float]
    warn_or_fail_ci: tuple[float, float]


def decide_all(
    left: RunResults,
    right: RunResults,
    policy: GatePolicy,
    rng: np.random.Generator,
    *,
    directions: Mapping[str, bool],
) -> dict[Variant, GateStatus]:
    """Decide one pair (``left`` = baseline, ``right`` = candidate) with all three variants."""
    production = evaluate_gate(left, right, policy, rng, directions=directions)
    return {
        "pruefstand": production.status,
        "naive": naive_gate(production, left, right, policy, directions=directions),
        "no_slices": no_slice_gate(left, right, policy, rng, directions=directions).status,
    }


def alarm_counts(status: GateStatus) -> tuple[int, int]:
    """``(fail, warn_or_fail)`` increments of one decision, counted as in amendment A1.

    Examples:
        >>> alarm_counts(GateStatus.UNSUPPORTED_CONFIG), alarm_counts(GateStatus.INSUFFICIENT_DATA)
        ((0, 1), (0, 0))
    """
    counted = counted_status(status)
    return int(counted is GateStatus.FAIL), int(counted in ALARM)


def replay_arm(
    pairs: PairFactory,
    policy: GatePolicy,
    *,
    directions: Mapping[str, bool],
    n: int,
    seed: int,
) -> list[ArmResult]:
    """Draw ``n`` pairs from ``pairs`` (one seeded generator) and count each variant's alarms."""
    rng = np.random.default_rng(seed)
    fails = dict.fromkeys(VARIANTS, 0)
    alarms = dict.fromkeys(VARIANTS, 0)
    for _ in range(n):
        left, right = pairs(rng)
        for variant, status in decide_all(left, right, policy, rng, directions=directions).items():
            fail, alarm = alarm_counts(status)
            fails[variant] += fail
            alarms[variant] += alarm
    return [
        ArmResult(
            variant=v,
            n=n,
            fail=fails[v],
            warn_or_fail=alarms[v],
            fail_ci=wilson_interval(fails[v], n),
            warn_or_fail_ci=wilson_interval(alarms[v], n),
        )
        for v in VARIANTS
    ]
