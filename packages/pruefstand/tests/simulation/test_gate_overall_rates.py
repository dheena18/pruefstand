"""Full-gate no-op simulation (testing-strategy §3.4, SPEC §7.2): ``evaluate_gate`` on noise only.

Simulated numbers because the true change must be known (0); this validates the gate maths
(one Holm family, absolute checks on ``overall``, informational slices), not the product. Grid size
by ``PRUEFSTAND_SIM_GRID``: ``reduced`` (default, 500 sims, bound + 4 SE) or ``full`` (nightly,
4 000 sims). If a bound fails, stop and report the numbers; never tune the rule or the bounds.
"""

import math
import os

import numpy as np
import pytest
from testsupport.sim_data import simulate_noop_runs

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.gate.policy import evaluate_gate

SEED = 20261028
FULL = os.environ.get("PRUEFSTAND_SIM_GRID", "reduced") == "full"
N_SIMS = 4000 if FULL else 500
N_RESAMPLES = 200
FAIL_BOUND, WARN_BOUND = 0.03, 0.12


def _bound(p: float) -> float:
    return p if FULL else p + 4 * math.sqrt(p * (1 - p) / N_SIMS)


POLICY = GatePolicy(
    metrics={
        **{
            m: MetricPolicy(max_drop=0.05)
            for m in (
                "faithfulness",
                "answer_correctness",
                "context_recall",
                "ndcg_at_k",
                "citation_recall",
            )
        },
        "language_match": MetricPolicy(max_drop=0.03),
        "false_refusal": MetricPolicy(max_drop=0.03),
        "refusal_correct": MetricPolicy(max_drop=0.10),
        "injection_success": MetricPolicy(max_value=0.02),
        "error_rate": MetricPolicy(max_value=0.02),
    },
    n_resamples=N_RESAMPLES,
)
DIRECTIONS = {m: m not in ("injection_success", "error_rate") for m in POLICY.metrics}
INFORMATIONAL = {"refusal_correct": "refusal_outside_nightly_full"}


@pytest.mark.slow
def test_full_gate_noop_error_rates() -> None:
    rng = np.random.default_rng(SEED)
    fails = warns = absolute = rerun_sims = rerun_pairs = pairs = 0
    for _ in range(N_SIMS):
        base, cand = simulate_noop_runs(rng)
        report = evaluate_gate(
            base, cand, POLICY, rng, directions=DIRECTIONS, informational=INFORMATIONAL
        )
        fails += report.status is GateStatus.FAIL
        warns += report.status in (GateStatus.WARN, GateStatus.FAIL)
        absolute += any(
            a.gated and a.status in (GateStatus.WARN, GateStatus.FAIL)
            for a in report.absolute_checks
        )
        testable = [d for d in report.decisions if d.status is not GateStatus.INSUFFICIENT_DATA]
        redone = [d for d in testable if d.result and d.result.n_resamples > N_RESAMPLES]
        pairs += len(testable)
        rerun_pairs += len(redone)
        rerun_sims += bool(redone)
    fail_share, warn_share = fails / N_SIMS, warns / N_SIMS
    print(  # noqa: T201  (the numbers are the evidence of T1.7)
        f"no-op gate ({'full' if FULL else 'reduced'} grid, {N_SIMS} sims, B={N_RESAMPLES}): "
        f"FAIL share {fail_share:.4f} (bound {_bound(FAIL_BOUND):.4f}), "
        f"WARN-or-FAIL share {warn_share:.4f} (bound {_bound(WARN_BOUND):.4f}), "
        f"share caused by absolute checks {absolute / N_SIMS:.4f}, "
        f"re-run counter {rerun_pairs} pairs in {rerun_sims} sims, "
        f"share of pairs decided at B=200000 {rerun_pairs / max(pairs, 1):.5f}"
    )
    assert fail_share <= _bound(FAIL_BOUND)
    assert warn_share <= _bound(WARN_BOUND)
    assert rerun_pairs > 0, "the adaptive B = 200 000 re-run never fired (vacuous simulation)"
