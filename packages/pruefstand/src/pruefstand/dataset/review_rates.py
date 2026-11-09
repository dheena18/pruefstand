"""Error rates and review rounds of the model review (T4.7a); re-exported by ``dataset.review``."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pruefstand.core.models.dataset import ReviewItem, ReviewRound

DETERMINISTIC = "deterministic"
REWRITE_FORBIDDEN = "reference_rewrite_forbidden"


@dataclass(frozen=True)
class StratumRate:
    """Review outcome of one stratum; ``error_rate`` = (fix + reject) / reviewed."""

    stratum: str
    reviewed: int
    fix: int
    reject: int
    error_rate: float
    needs_regeneration: bool


def normalise_item(item: ReviewItem, *, reject_only: bool = True) -> ReviewItem:
    """Apply the reject-only rule: a ``fix`` that rewrites the reference becomes a ``reject``.

    A ``fix`` with neither a new question nor a new answer is also a ``reject`` (nothing to apply).
    """
    if item.verdict != "fix":
        return item
    if item.fixed_answer and reject_only:
        return item.model_copy(
            update={"verdict": "reject", "reasons": (*item.reasons, REWRITE_FORBIDDEN)}
        )
    if not item.fixed_question and not item.fixed_answer:
        return item.model_copy(
            update={"verdict": "reject", "reasons": (*item.reasons, "fix_without_text")}
        )
    return item


def reviewed_items(items: Sequence[ReviewItem], *, reject_only: bool) -> list[ReviewItem]:
    """The normalised items that went to a model (deterministic-only items carry no rate)."""
    seen = (normalise_item(i, reject_only=reject_only) for i in items)
    return [i for i in seen if i.model != DETERMINISTIC]


def _rate(key: str, group: Sequence[ReviewItem], threshold: float) -> StratumRate:
    counts = Counter(i.verdict for i in group)
    bad = counts["fix"] + counts["reject"]
    return StratumRate(
        stratum=key,
        reviewed=len(group),
        fix=counts["fix"],
        reject=counts["reject"],
        error_rate=bad / len(group),
        needs_regeneration=bad > threshold * len(group) + 1e-9,
    )


def error_rates(
    items: Sequence[ReviewItem], *, threshold: float = 0.10, reject_only: bool = True
) -> dict[str, StratumRate]:
    """Return the model error rate per stratum (``<category>/<prompt version>``).

    Args:
        items: Review results; items without a model call (``model == "deterministic"``) are left
            out, they carry no rate.
        threshold: A stratum with a rate above this needs regeneration.
        reject_only: Apply the reject-only rule first (a rewritten answer counts as a reject).

    Returns:
        The strata in sorted order.
    """
    groups: dict[str, list[ReviewItem]] = defaultdict(list)
    for item in reviewed_items(items, reject_only=reject_only):
        groups[f"{item.category}/{item.prompt_version}"].append(item)
    return {key: _rate(key, groups[key], threshold) for key in sorted(groups)}


def rounds_of(
    items: Sequence[ReviewItem], reviewer: str, today: date, first: int
) -> tuple[ReviewRound, ...]:
    """Return one ``ReviewRound`` per generation prompt version, numbered from ``first``."""
    groups: dict[str, list[ReviewItem]] = defaultdict(list)
    for item in items:
        groups[item.prompt_version].append(item)
    rounds: list[ReviewRound] = []
    for offset, version in enumerate(sorted(groups)):
        group = groups[version]
        bad = sum(1 for i in group if i.verdict != "ok")
        rounds.append(
            ReviewRound(
                round=first + offset,
                prompt_version=version,
                sampled=len(group),
                bad=bad,
                error_rate=bad / len(group),
                reviewer=reviewer,
                date=today,
            )
        )
    return tuple(rounds)
