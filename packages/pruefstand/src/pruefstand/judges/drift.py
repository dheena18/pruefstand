"""Judge drift on fixed anchor items (T5.4 S10/S11; interfaces §6, D114, D253, D308).

The nightly re-judges the 50 stored anchors of a pinned judge with the cache bypassed;
``anchor_agreement`` compares the raw scores, ``is_drift`` applies the rule. ``drift_threshold``
derives a judge's own threshold from its measured flip rate (AI13-07). Since T5.4d the stored
verdict of an anchor is the majority of several runs (``majority_scores``) and the flip rate is
counted on further runs against it (``count_flips``, D1250).
"""

import math
from collections import Counter
from collections.abc import Sequence

from scipy import stats

from pruefstand.core.models.judge import JudgeVerdict
from pruefstand.judges.calibration import wilson_interval

MAX_FALSE_DRIFT = 0.01
"""Largest accepted probability of a false drift alarm per night (AI13-07)."""


def anchor_agreement(stored: Sequence[JudgeVerdict], fresh: Sequence[JudgeVerdict]) -> float:
    """Share of anchors whose fresh ``raw_score`` equals the stored one.

    Args:
        stored: Verdicts recorded with the anchor set, in anchor order.
        fresh: Verdicts of tonight's re-judging, same order.

    Returns:
        Agreement in [0, 1].

    Raises:
        ValueError: Different lengths or no anchors.

    Examples:
        >>> def v(s: int) -> JudgeVerdict:
        ...     return JudgeVerdict(score=s / 2, reason="", raw_score=s, judge_model="m",
        ...                         cached=False)
        >>> anchor_agreement([v(2), v(0), v(1), v(2)], [v(2), v(0), v(2), v(2)])
        0.75
    """
    if len(stored) != len(fresh):
        msg = f"anchor verdicts differ in length ({len(stored)} vs {len(fresh)})"
        raise ValueError(msg)
    if not stored:
        msg = "no anchor verdicts"
        raise ValueError(msg)
    same = sum(1 for s, f in zip(stored, fresh, strict=True) if s.raw_score == f.raw_score)
    return same / len(stored)


def default_threshold(n: int) -> int:
    """The N3 rule (D253): ``max(3, ceil(0.1 * n))`` changed anchors (n = 50 -> 5).

    Examples:
        >>> default_threshold(50), default_threshold(20)
        (5, 3)
    """
    return max(3, math.ceil(0.1 * n))


def threshold_cap(n: int) -> int:
    """Largest acceptable drift threshold: twice the N3 default (n = 50 -> 10; D945).

    A judge whose flip rate needs more is unfit for the anchor drift check.

    Examples:
        >>> threshold_cap(50)
        10
    """
    return 2 * default_threshold(n)


def is_drift(
    agreement: float, n: int, *, a0: float | None = None, threshold: int | None = None
) -> bool:
    """Whether the anchor re-run shows drift.

    ``changed = n - round(agreement * n)``; drift iff ``changed >= threshold`` (default the N3
    rule). ``a0`` (self-agreement) is accepted for the record and never enters the decision.

    Args:
        agreement: ``anchor_agreement`` of tonight's run.
        n: Number of anchors.
        a0: The judge's self-agreement (recorded only, AI12-03).
        threshold: The judge's calibrated threshold (``calibration_status.yaml``, D308).

    Returns:
        True on drift.

    Raises:
        ValueError: ``n < 1``, ``agreement`` outside [0, 1], or a threshold below the default
            or above ``threshold_cap(n)``.

    Examples:
        >>> is_drift(0.92, 50), is_drift(0.90, 50), is_drift(0.98, 50, a0=1.0)
        (False, True, False)
        >>> is_drift(0.86, 50, threshold=8), is_drift(0.84, 50, threshold=8)
        (False, True)
    """
    del a0  # recorded in judge_drift.json by the caller, never part of the decision (D253)
    if n < 1 or not 0.0 <= agreement <= 1.0:
        msg = f"need n >= 1 and 0 <= agreement <= 1 (got n={n}, agreement={agreement})"
        raise ValueError(msg)
    floor = default_threshold(n)
    if threshold is not None and threshold < floor:
        msg = f"drift threshold {threshold} is below the default {floor} for n={n}"
        raise ValueError(msg)
    if threshold is not None and threshold > threshold_cap(n):
        msg = f"drift threshold {threshold} is above the cap {threshold_cap(n)}: judge unfit (D945)"
        raise ValueError(msg)
    changed = n - round(agreement * n)
    return changed >= (floor if threshold is None else threshold)


def flip_rate(flips: int, comparisons: int) -> tuple[float, float]:
    """Per-anchor flip rate and its 95 % Wilson upper bound.

    A flip is a repeated judging of an anchor whose raw score differs from the first one.

    Raises:
        ValueError: ``comparisons < 1`` or ``flips`` outside ``[0, comparisons]``.

    Examples:
        >>> tuple(round(x, 4) for x in flip_rate(2, 150))
        (0.0133, 0.0473)
    """
    _, high = wilson_interval(flips, comparisons)
    return flips / comparisons, high


def majority_scores(runs: Sequence[Sequence[int]]) -> list[int]:
    """Per anchor, the most frequent raw score over ``runs`` (T5.4d, D1250).

    A tie goes to the tied score that occurs in the earliest run, so the result is deterministic.

    Args:
        runs: One list of raw scores per run, every run in anchor order.

    Returns:
        The majority score per anchor.

    Raises:
        ValueError: No runs, or runs of different lengths.

    Examples:
        Anchor 2 is 1 in three of five runs; anchor 3 ties 2:2 (0 then 2 in run order), so 0:

        >>> majority_scores([[2, 0, 1, 0], [2, 0, 1, 2], [2, 0, 0, 2], [2, 1, 1, 0], [2, 0, 0, 1]])
        [2, 0, 1, 0]
    """
    if not runs or len({len(run) for run in runs}) != 1:
        msg = "need at least one run and runs of equal length"
        raise ValueError(msg)
    out: list[int] = []
    for column in zip(*runs, strict=True):
        counts = Counter(column)
        top = max(counts.values())
        out.append(next(score for score in column if counts[score] == top))
    return out


def count_flips(stored: Sequence[int], runs: Sequence[Sequence[int]]) -> tuple[int, int]:
    """Flips against the stored scores: ``(differing judgings, comparisons)`` over ``runs``.

    Raises:
        ValueError: A run's length differs from ``stored``.

    Examples:
        >>> count_flips([2, 0, 1], [[2, 0, 1], [2, 1, 1], [0, 1, 1]])
        (3, 9)
    """
    if any(len(run) != len(stored) for run in runs):
        msg = "every run needs one score per stored anchor"
        raise ValueError(msg)
    flips = sum(1 for run in runs for a, b in zip(stored, run, strict=True) if a != b)
    return flips, len(stored) * len(runs)


def unstable_anchors(runs: Sequence[Sequence[int]], min_share: float = 0.8) -> list[int]:
    """Indices of anchors whose most frequent score has a share below ``min_share`` (D1250).

    Such an anchor flips between scores at temperature 0 (e.g. 2, 1, 2, 1, 2, 1, 1, 1, 1);
    the T5.4d screening replaces it. A single odd run in nine (share 8/9) is not unstable.

    Raises:
        ValueError: No runs, or runs of different lengths.

    Examples:
        >>> unstable_anchors([[0, 2, 2], [1, 0, 1], [1, 0, 2], [1, 0, 1], [1, 0, 2]])
        [2]
    """
    if not runs or len({len(run) for run in runs}) != 1:
        msg = "need at least one run and runs of equal length"
        raise ValueError(msg)
    return [
        k
        for k, column in enumerate(zip(*runs, strict=True))
        if max(Counter(column).values()) / len(column) < min_share
    ]


def drift_threshold(f_upper: float, n: int = 50, alpha: float = MAX_FALSE_DRIFT) -> int:
    """Smallest c >= the N3 default with ``P(Bin(n, f_upper) >= c) <= alpha`` (AI13-07, D308).

    Args:
        f_upper: Upper CI bound of the per-anchor flip rate.
        n: Number of anchors.
        alpha: Accepted false-alarm probability per night.

    Returns:
        The judge's threshold, at most ``threshold_cap(n)``.

    Raises:
        ValueError: ``f_upper`` outside [0, 1], ``n < 1``, or the needed threshold is above
            ``threshold_cap(n)``: the judge is unfit for the drift check (D945).

    Examples:
        P(Bin(50, 0.06) >= 7) = 0.029 > 0.01, P(>= 8) = 0.009:

        >>> drift_threshold(0.02), drift_threshold(0.06)
        (5, 8)
    """
    if n < 1 or not 0.0 <= f_upper <= 1.0:
        msg = f"need n >= 1 and 0 <= f_upper <= 1 (got n={n}, f_upper={f_upper})"
        raise ValueError(msg)
    for c in range(default_threshold(n), threshold_cap(n) + 1):
        if float(stats.binom.sf(c - 1, n, f_upper)) <= alpha:
            return c
    cap = threshold_cap(n)
    msg = f"flip rate upper bound {f_upper:.3f} needs a threshold above {cap}: judge unfit"
    raise ValueError(msg)
