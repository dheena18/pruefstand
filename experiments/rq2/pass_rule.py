"""The calibration pass rule (D146, round 9 X1.1) and the refusal-judge rule (D193, AI9-19).

Per metric a judge passes only if, on **every** gating label set (faithfulness: MEMERAG and
``legal_hard``; answer_correctness: ``correctness`` and ``legal_hard``):

1. binary kappa >= 0.6 on the full set, and
2. specificity >= 0.80 on the hard-negative subset with its 95 % Wilson lower bound >= 0.70,

and (3) discrimination >= 0.90 per edit type. A gating set that is not built yet makes the metric
``pending`` (never ``passed``). The thresholds are constants: never lower them.
Dev/test (AI13-12): the rule runs on ``test`` items only; prompt and judge choices on ``dev`` only.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from rq2.calib_schema import CalibrationItem

KAPPA_MIN = 0.6
SPECIFICITY_MIN = 0.80
SPECIFICITY_LOW_MIN = 0.70
DISCRIMINATION_MIN = 0.90
REFUSAL_ACCURACY_MIN = 0.95
REFUSAL_HEDGED_FPR_MAX = 0.05
Status = Literal["passed", "failed", "pending"]


@dataclass(frozen=True)
class SetEvidence:
    """What one gating label set says about a judge and a metric (``test`` split)."""

    kappa: float | None
    specificity: float | None
    specificity_low: float | None


@dataclass(frozen=True)
class Outcome:
    """Pass-rule result of one judge and metric."""

    status: Status
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True only for ``passed`` (``pending`` is not a pass)."""
        return self.status == "passed"


def require_split(items: Iterable[CalibrationItem], split: Literal["dev", "test"]) -> None:
    """Refuse items of the other split (AI13-12).

    Raises:
        ValueError: An item has another ``calib_split``.
    """
    wrong = [i.item_id for i in items if i.calib_split != split]
    if wrong:
        msg = f"{len(wrong)} item(s) are not in the {split!r} split (first: {wrong[0]})"
        raise ValueError(msg)


def pass_rule_items(items: Sequence[CalibrationItem]) -> Sequence[CalibrationItem]:
    """The items the pass rule may use: ``test`` only (``ValueError`` on a ``dev`` item)."""
    require_split(items, "test")
    return items


def selection_items(items: Sequence[CalibrationItem]) -> Sequence[CalibrationItem]:
    """The items prompt work and judge choice may use: ``dev`` only (``ValueError`` on ``test``)."""
    require_split(items, "dev")
    return items


def _set_reasons(name: str, ev: SetEvidence) -> list[str]:
    reasons = []
    if ev.kappa is None or ev.kappa < KAPPA_MIN:
        reasons.append(f"{name}: kappa {ev.kappa} < {KAPPA_MIN}")
    if ev.specificity is None or ev.specificity < SPECIFICITY_MIN:
        reasons.append(f"{name}: hard-negative specificity {ev.specificity} < {SPECIFICITY_MIN}")
    if ev.specificity_low is None or ev.specificity_low < SPECIFICITY_LOW_MIN:
        reasons.append(
            f"{name}: specificity Wilson low {ev.specificity_low} < {SPECIFICITY_LOW_MIN}"
        )
    return reasons


def metric_outcome(
    evidence: Mapping[str, SetEvidence],
    required: Sequence[str],
    discrimination: Mapping[str, float],
) -> Outcome:
    """Apply the pass rule to one judge and metric.

    Args:
        evidence: Per evaluated gating set, its ``test`` numbers.
        required: The gating sets of the metric (``rq2_judges.yaml`` ``gating``).
        discrimination: Share of strictly lower degraded scores per edit type.

    Returns:
        ``failed`` if any evaluated criterion fails, else ``pending`` if a required set has no
        evidence yet, else ``passed``.
    """
    reasons: list[str] = []
    for name in required:
        if name in evidence:
            reasons += _set_reasons(name, evidence[name])
    if not discrimination:
        reasons.append("no discrimination pairs")
    reasons += [
        f"discrimination {edit} {value:.3f} < {DISCRIMINATION_MIN}"
        for edit, value in sorted(discrimination.items())
        if not value >= DISCRIMINATION_MIN
    ]
    if reasons:
        return Outcome("failed", tuple(reasons))
    missing = [name for name in required if name not in evidence]
    if missing:
        return Outcome(
            "pending", tuple(f"{name}: not evaluated (set not built)" for name in missing)
        )
    return Outcome("passed")


def refusal_outcome(
    labels: Sequence[int], preds: Sequence[int], hard_types: Sequence[str | None]
) -> Outcome:
    """The ``refusal_judged`` rule: accuracy >= 0.95 and FPR <= 0.05 on ``hedged_answer`` items.

    A false positive is a judge "refusal" (1) on a ``hedged_answer`` item (label 0).
    """
    n = len(labels)
    accuracy = sum(1 for y, p in zip(labels, preds, strict=True) if y == p) / n
    hedged = [p for p, t in zip(preds, hard_types, strict=True) if t == "hedged_answer"]
    fpr = sum(hedged) / len(hedged) if hedged else float("nan")
    reasons = []
    if accuracy < REFUSAL_ACCURACY_MIN:
        reasons.append(f"accuracy {accuracy:.3f} < {REFUSAL_ACCURACY_MIN}")
    if not fpr <= REFUSAL_HEDGED_FPR_MAX:
        reasons.append(f"hedged_answer FPR {fpr:.3f} > {REFUSAL_HEDGED_FPR_MAX}")
    return Outcome("failed", tuple(reasons)) if reasons else Outcome("passed")
