"""RQ3 scoring (T7.2 S4, pure core): decisions x 3 variants -> detection, false block, false warn.

Pre-registered rules (``PREREGISTRATION.md``, round 13 P3.3): detection is a **FAIL** only (a WARN
is counted separately, never as detection); the detection denominator is the **should-detect**
``statistical`` mutations (true effect >= delta on the reference arm); a ``statistical`` mutation
below delta goes to its own row ("flagged anyway" when it FAILs); ``deterministic`` mutations have
their own detection row; ``normaliser`` (M20) only reports its PASS rate; no-ops give the
false-block (FAIL) and false-warn (WARN) rates. Every rate has a Wilson 95 % interval; one table
per tier.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Literal

from mutations.schema import MutationSpec
from pydantic import BaseModel, ConfigDict

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import ConfigError
from pruefstand.gate.stats import wilson_interval

Variant = Literal["pruefstand", "naive", "no_slices"]
Tier = Literal["pr", "nightly"]
Outcome = Literal[
    "detection_statistical",
    "warn_statistical",
    "below_delta_flagged",
    "detection_deterministic",
    "normaliser_pass",
    "false_block",
    "false_warn",
]
ALSO_NIGHTLY = frozenset({"M14", "M15", "M20"})  # also in the nightly table (X3.10)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Decision(_Frozen):
    """One scored run: entry, repeat, gate variant, tier, decided status."""

    entry: str
    rep: int
    variant: Variant
    tier: Tier
    status: GateStatus


class Rate(_Frozen):
    """``k`` of ``n`` with its Wilson 95 % interval (``rate`` None when ``n`` is 0)."""

    k: int
    n: int
    rate: float | None
    ci_low: float
    ci_high: float


class SummaryRow(_Frozen):
    """One cell of the summary table."""

    variant: Variant
    tier: Tier
    outcome: Outcome
    rate: Rate


def rate(k: int, n: int) -> Rate:
    """Return ``k / n`` with its Wilson 95 % interval.

    Examples:
        >>> r = rate(0, 30)
        >>> (r.rate, r.ci_low, round(r.ci_high, 3))
        (0.0, 0.0, 0.114)
    """
    low, high = wilson_interval(k, n)
    return Rate(k=k, n=n, rate=k / n if n else None, ci_low=low, ci_high=high)


def _outcomes(
    spec: MutationSpec, should_detect: Mapping[str, bool]
) -> list[tuple[Outcome, GateStatus]]:
    """The (outcome, counted status) pairs one decision of ``spec`` contributes to."""
    if spec.is_noop:
        return [("false_block", GateStatus.FAIL), ("false_warn", GateStatus.WARN)]
    if spec.stratum == "normaliser":
        return [("normaliser_pass", GateStatus.PASS)]
    if spec.stratum == "deterministic":
        return [("detection_deterministic", GateStatus.FAIL)]
    if spec.id not in should_detect:
        msg = f"{spec.id}: no true-effect result (should-detect is decided before scoring, P3.3)"
        raise ConfigError(msg)
    if should_detect[spec.id]:
        return [("detection_statistical", GateStatus.FAIL), ("warn_statistical", GateStatus.WARN)]
    return [("below_delta_flagged", GateStatus.FAIL)]


def _check_tier(decision: Decision, spec: MutationSpec) -> None:
    allowed = {spec.tier} | ({"nightly"} if spec.id in ALSO_NIGHTLY else set())
    if decision.tier not in allowed:
        msg = (
            f"{decision.entry}: scored in tier {decision.tier}, declared {sorted(allowed)} (X3.10)"
        )
        raise ConfigError(msg)


def summarise(
    decisions: Iterable[Decision],
    specs: Mapping[str, MutationSpec],
    should_detect: Mapping[str, bool],
) -> list[SummaryRow]:
    """Count every outcome per variant and tier.

    Args:
        decisions: The scored runs (re-runs after infra errors are already replaced).
        specs: ``mutation.yaml`` of every scored entry, by id.
        should_detect: statistical mutation id -> true effect >= delta (``true_effect.csv``).

    Returns:
        One row per (variant, tier, outcome) that has decisions, sorted.

    Raises:
        ConfigError: an unknown entry, a decision in a tier the entry does not declare, or a
            statistical mutation without a true-effect result.
    """
    counts: dict[tuple[Variant, Tier, Outcome], list[int]] = defaultdict(lambda: [0, 0])
    for decision in decisions:
        spec = specs.get(decision.entry)
        if spec is None:
            msg = f"{decision.entry}: not an entry of benchmarks/mutations/index.yaml"
            raise ConfigError(msg)
        _check_tier(decision, spec)
        for outcome, counted in _outcomes(spec, should_detect):
            cell = counts[(decision.variant, decision.tier, outcome)]
            cell[0] += decision.status is counted
            cell[1] += 1
    return [
        SummaryRow(variant=v, tier=t, outcome=o, rate=rate(k, n))
        for (v, t, o), (k, n) in sorted(counts.items())
    ]


def matches_expected(decision: Decision, spec: MutationSpec) -> bool:
    """Whether the decided status equals ``expected.status`` of ``mutation.yaml``."""
    return decision.status.value == spec.expected.status.lower()
