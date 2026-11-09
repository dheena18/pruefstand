"""Baseline-side caps of the pairing (T1.7a): what baseline ``error`` values may do to a slice.

Baseline ``error`` values are excluded from pairing. Two limits keep that from hiding a slice:
at most 20 % of the slice's *applicable* baseline cases (``ok`` or ``error``; ``not_applicable``
never counts), and the slice must keep ``min_clusters`` clusters. Either breach is a
``GateInputError``: the baseline cannot judge that slice.
"""

import numpy as np

from pruefstand.gate._validate import fail
from pruefstand.gate.slices import universe_members
from pruefstand.gate.tables import PairedTable

MAX_EXCLUDED_FRACTION = 0.20  # judge/baseline errors beyond this share of a slice are not dropped


def check_baseline_slice(
    table: PairedTable, dimension: str, value: str, min_clusters: int, *, cap: bool = True
) -> None:
    """Fail when baseline ``error`` values make a slice untestable or exceed the cap.

    A slice with fewer than ``min_clusters`` applicable clusters is skipped: it can never be
    testable, its row is ``INSUFFICIENT_DATA`` anyway and a few random baseline errors must not
    make every PR against that baseline fail.

    Args:
        table: The paired table of one metric.
        dimension: Slice dimension (``overall`` included).
        value: Slice value.
        min_clusters: Clusters the slice needs to be testable.
        cap: Also enforce the 20 % cap (the cluster check always runs).

    Raises:
        GateInputError: Baseline errors cover more than 20 % of the applicable cases, or leave
            fewer than ``min_clusters`` of the applicable clusters.
    """
    applicable = universe_members(table, dimension, value) & table.all_base_applicable
    before = int(np.unique(table.all_clusters[applicable]).size)
    if before < min_clusters:
        return
    total, bad = int(applicable.sum()), int((applicable & table.all_base_error).sum())
    if cap and bad > MAX_EXCLUDED_FRACTION * total + 1e-9:
        fail(
            f"{table.metric}: baseline errors on {bad} of {total} cases of "
            f"{dimension}={value}; the baseline cannot judge this slice; "
            "re-run the baseline or promote a run with fewer judge errors"
        )
    kept = applicable & ~table.all_base_error
    after = int(np.unique(table.all_clusters[kept]).size)
    if after < min_clusters:
        fail(
            f"{table.metric}: baseline errors leave {after} of {before} clusters of "
            f"{dimension}={value}, fewer than {min_clusters}; "
            "the baseline cannot judge this slice; "
            "re-run the baseline or promote a run with fewer judge errors"
        )
