"""Multiple-comparison adjustment: Holm (family-wise) and Benjamini-Hochberg (FDR).

Both return adjusted p-values in the **original order**, clipped to at most 1.
"""

from collections.abc import Sequence

from pruefstand.gate._validate import fail


def _checked(p_values: Sequence[float]) -> list[float]:
    ps = [float(p) for p in p_values]
    # `not 0 <= p <= 1` is also true for NaN
    if any(not 0.0 <= p <= 1.0 for p in ps):
        fail("p-values must lie in [0, 1] and be finite")
    return ps


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm step-down adjustment (controls the family-wise error rate).

    Sort ascending; the i-th smallest of m p-values is multiplied by ``m - i`` (i from 0), a running
    maximum keeps the sequence monotone, and everything is clipped to 1.

    Args:
        p_values: Raw p-values in [0, 1].

    Returns:
        Adjusted p-values in the input order; ``[]`` for empty input.

    Raises:
        GateInputError: A p-value is NaN, infinite or outside [0, 1].

    Examples:
        >>> [round(p, 3) for p in holm_adjust([0.01, 0.04, 0.03, 0.005])]
        [0.03, 0.06, 0.06, 0.02]
        >>> holm_adjust([0.6, 0.9])
        [1.0, 1.0]
    """
    ps = _checked(p_values)
    m = len(ps)
    out = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(sorted(range(m), key=ps.__getitem__)):
        running = max(running, min(1.0, ps[idx] * (m - rank)))
        out[idx] = running
    return out


def bh_adjust(p_values: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjustment (controls the false discovery rate).

    The i-th smallest of m p-values (i from 1) becomes ``p * m / i``; a running minimum from the
    largest down keeps the sequence monotone; clipped to 1.

    Args:
        p_values: Raw p-values in [0, 1].

    Returns:
        Adjusted p-values in the input order; ``[]`` for empty input.

    Raises:
        GateInputError: A p-value is NaN, infinite or outside [0, 1].

    Examples:
        >>> [round(p, 3) for p in bh_adjust([0.01, 0.04, 0.03, 0.005])]
        [0.02, 0.04, 0.04, 0.02]
    """
    ps = _checked(p_values)
    m = len(ps)
    out = [0.0] * m
    running = 1.0
    order = sorted(range(m), key=ps.__getitem__)
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        running = min(running, ps[idx] * m / rank)
        out[idx] = running
    return out
