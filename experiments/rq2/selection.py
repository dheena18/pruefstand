"""Judge selection (ADR-0019, D112) and the ``calibration_status.yaml`` document (T5.4 S8/S11).

Gating judge: (a) ``gemma3:12b`` if it passes every gated metric; else the cheapest passing (a')
candidate; if none passes, the best-kappa local judge is pinned anyway with ``passed: false``
(judged
metrics informational in both tiers, W3.8). Tier-1 informational judge: the best GitHub Models
candidate on the publishable ``faithfulness_constructed`` set (the public datagen family is compared
on faithfulness only, AI9-26); without measurements the provisional pin stays.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rq2.pass_rule import Outcome


@dataclass(frozen=True)
class Candidate:
    """One measured local judge."""

    judge: str
    arm: str
    outcomes: Mapping[str, Outcome]
    mean_kappa: float
    gpu_s_per_1k: float

    @property
    def passed(self) -> bool:
        """Passed every gated metric."""
        return bool(self.outcomes) and all(o.passed for o in self.outcomes.values())


@dataclass(frozen=True)
class Selection:
    """The pinned gating judge and whether it passed."""

    judge: str
    passed: bool
    reason: str


def select_gating(candidates: Sequence[Candidate], primary: str) -> Selection:
    """Pick the gating judge for PR and nightly (one model).

    Raises:
        ValueError: No candidate at all.
    """
    if not candidates:
        msg = "no measured judge"
        raise ValueError(msg)
    by_id = {c.judge: c for c in candidates}
    if primary in by_id and by_id[primary].passed:
        return Selection(primary, passed=True, reason="(a) passes the pass rule")
    passing = sorted((c for c in candidates if c.passed), key=lambda c: (c.gpu_s_per_1k, c.judge))
    if passing:
        return Selection(passing[0].judge, passed=True, reason="cheapest passing (a') candidate")
    best = max(candidates, key=lambda c: (c.mean_kappa, c.judge == primary))
    return Selection(
        best.judge,
        passed=False,
        reason="no judge passes: best-kappa local judge pinned, informational",
    )


def select_tier1(
    kappas: Mapping[str, Mapping[str, float]], families: Mapping[str, str], datagen_family: str
) -> str | None:
    """Pick the tier-1 informational judge from measured GitHub Models candidates.

    Args:
        kappas: Per judge, kappa per label set (``all`` stratum, common subsample).
        families: Family of each judge.
        datagen_family: The public datagen family (compared on faithfulness only).

    Returns:
        The judge id, or None when nothing was measured.
    """
    scored = {
        judge: per_set["faithfulness_constructed"]
        for judge, per_set in kappas.items()
        if "faithfulness_constructed" in per_set and families.get(judge) != "qwen"
    }
    if not scored:
        return None
    best = max(scored.values())
    ties = sorted(j for j, k in scored.items() if k == best)
    others = [j for j in ties if families.get(j) != datagen_family]
    return (others or ties)[0]
