"""Promote-time check of a baseline candidate (T1.7a): can the gate still judge every gated slice?

``evaluate_gate`` raises ``GateInputError`` when baseline ``error`` values exceed 20 % of a
testable gated slice or leave it under ``min_clusters`` clusters (``gate/_baseline.py``). A run with
such errors would make *every* PR against that baseline fail, so ``pruefstand baseline promote``
runs the same check first and refuses the run (the gate-side raise stays as a backstop).
"""

from collections.abc import Mapping

from pruefstand.core.config import GatePolicy
from pruefstand.core.models.run import RunResults
from pruefstand.gate._baseline import check_baseline_slice
from pruefstand.gate.slices import slice_values
from pruefstand.gate.tables import OVERALL, PERTURBED_ALL, pair_runs


def check_baseline_run(run: RunResults, policy: GatePolicy, directions: Mapping[str, bool]) -> None:
    """Fail when ``run`` could not serve as a baseline for the gated slices of ``policy``.

    Args:
        run: The run proposed as a baseline.
        policy: The gate policy (paired metrics, gated slices, ``min_clusters``).
        directions: metric -> ``higher_is_better``; metrics without an entry are skipped.

    Raises:
        GateInputError: Baseline ``error`` values cover more than 20 % of the applicable cases of
            a testable gated slice, or leave it fewer than ``min_clusters`` clusters. Re-run the
            baseline (or promote a run with fewer judge errors).
    """
    for metric, metric_policy in sorted(policy.metrics.items()):
        if metric_policy.max_drop is None or metric not in directions:
            continue
        table = pair_runs(run, run, metric, higher_is_better=directions[metric])
        for dimension in policy.gated_slices:
            values = (
                (dimension,) if dimension in (OVERALL, PERTURBED_ALL)
                else slice_values(table, dimension)
            )  # fmt: skip
            for value in values:
                check_baseline_slice(table, dimension, value, policy.min_clusters)
