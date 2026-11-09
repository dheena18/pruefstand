"""Promote-time check of a baseline candidate (T1.7a): can the gate still judge every gated slice?

``evaluate_gate`` raises ``GateInputError`` when baseline ``error`` values exceed 20 % of a
testable gated slice or leave it under ``min_clusters`` clusters (``gate/_baseline.py``). A run with
such errors would make *every* PR against that baseline fail, so ``pruefstand baseline promote``
runs the same check first and refuses the run (the gate-side raise stays as a backstop). The
slices are those of the pairing (``gate.slices.slice_specs``) filtered by ``gated_slices``.
"""

from collections.abc import Collection, Mapping

from pruefstand.core.config import GatePolicy
from pruefstand.core.models.run import RunResults
from pruefstand.gate._baseline import check_baseline_slice
from pruefstand.gate.slices import slice_specs
from pruefstand.gate.tables import pair_runs


def check_baseline_run(
    run: RunResults,
    policy: GatePolicy,
    directions: Mapping[str, bool],
    skip: Collection[str] = (),
) -> None:
    """Fail when ``run`` could not serve as a baseline for the gated slices of ``policy``.

    Args:
        run: The run proposed as a baseline.
        policy: The gate policy (paired metrics, gated slices, ``min_clusters``).
        directions: metric -> ``higher_is_better``; metrics without an entry are skipped.
        skip: Metrics the gate treats as informational for this baseline (the gate does not
            check those); the caller decides, as the pipeline does for ``informational``.

    Raises:
        GateInputError: Baseline ``error`` values cover more than 20 % of the applicable cases of
            a testable gated slice, or leave it fewer than ``min_clusters`` clusters. Re-run the
            baseline (or promote a run with fewer judge errors).
    """
    for metric, metric_policy in sorted(policy.metrics.items()):
        if metric_policy.max_drop is None or metric not in directions or metric in skip:
            continue
        table = pair_runs(run, run, metric, higher_is_better=directions[metric])
        for dimension, value in slice_specs(table, policy):
            if dimension in policy.gated_slices:
                check_baseline_slice(table, dimension, value, policy.min_clusters)
