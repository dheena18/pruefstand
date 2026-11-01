"""``evaluate_gate``: two runs in, a complete ``GateReport`` out (SPEC §7.2, ADR-0007, T1.7).

Pure: numbers in, decision out (no I/O, no LLM, no clock; randomness only through ``rng``). Order
of work, all part of the contract (two implementations must produce identical JSON):

1. **Validate**: same ``eval_fingerprint``, both runs ``complete``, baseline ``error_rate`` mean
   at most ``max_error_rate``, a direction for every policy metric (``GateInputError``).
2. **Hard fails** (``hard_fail.py``): leaks with value 1, no statistics.
3. **Pairing** per paired metric (``tables.py``): join on ``case_id``; baseline not ``ok`` or a
   judge error excludes a pair; candidate ``not_applicable``/request error gets the worst value.
4. **Slices** (round 9 X3.6): an unperturbed case is in ``overall``, ``tenant``, ``lang``,
   ``category``, ``tags``; a perturbed case only in ``perturbed_all`` and ``perturbation=<p>``.
5. **Gated pairs**: per metric with ``max_drop`` that is not informational: ``overall`` + each value
   of the ``gated_slices`` dimensions + ``perturbed_all`` for ``context_recall``/``ndcg_at_k``.
   Testable iff ``n_clusters >= min_clusters``. A metric is informational when the pipeline says so
   (``informational``) or when its ``overall`` pair has fewer than 30 applicable clusters.
6. **Relative checks** (``pairs.py``): paired cluster bootstrap on every pair in the order metrics
   sorted by name, then ``overall``, ``perturbed_all``, the ``slices`` dimensions in order, values
   sorted, one ``rng``; ONE Holm family over all testable gated pairs; Benjamini-Hochberg over the
   informational ones (``notable``); adaptive B = 200 000 re-run near Holm thresholds.
7. **Absolute checks** (``absolute.py``): ``max_value`` metrics on ``overall``, Wilson rule.
8. **Status**: FAIL on a hard fail or a gated FAIL; else WARN on a gated WARN or
   ``counts["unsupported_config"] > 0``; else PASS. Informational and ``INSUFFICIENT_DATA`` never
   change it.
9. **Likely cause** (``cause.py``), 10. **top failing cases**: up to 5 unperturbed cases with the
   most negative oriented difference (minimum over the metrics whose gated ``overall`` decision is
   WARN or FAIL), ties by case id. 11. **Order**: ``decisions`` = gated pairs in step-6 order;
   ``notable_slices`` = all informational pairs, notable first, then ``mean_diff`` ascending, then
   (metric, dimension, value).
"""

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from pruefstand.core.config import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults
from pruefstand.gate._validate import fail
from pruefstand.gate.absolute import absolute_checks
from pruefstand.gate.cause import likely_cause
from pruefstand.gate.hard_fail import find_hard_fails
from pruefstand.gate.pairs import (
    Pair,
    bootstrap_pairs,
    build_decisions,
    informational_reason,
    metric_pairs,
)
from pruefstand.gate.tables import OVERALL, PairedTable, pair_runs, slice_members

_NO_INFORMATIONAL: Mapping[str, str] = MappingProxyType({})
_TOP_CASES = 5
_FAILING = frozenset({GateStatus.WARN, GateStatus.FAIL})


def _validate(
    baseline: RunResults, candidate: RunResults, policy: GatePolicy, directions: Mapping[str, bool]
) -> None:
    if baseline.manifest.eval_fingerprint != candidate.manifest.eval_fingerprint:
        fail("eval_fingerprint differs between baseline and candidate; the runs are not comparable")
    for name, run in (("baseline", baseline), ("candidate", candidate)):
        if not run.manifest.complete:
            fail(f"the {name} run is not complete (stop_reason={run.manifest.stop_reason!r})")
    errors = [
        v.value
        for s in baseline.values
        for v in s.values
        if v.metric == "error_rate" and v.status is MetricStatus.OK and v.value is not None
    ]
    if errors and sum(errors) / len(errors) > policy.max_error_rate:
        fail(f"baseline error_rate {sum(errors) / len(errors):.4f} exceeds {policy.max_error_rate}")
    for metric in policy.metrics:
        if metric not in directions:
            fail(f"directions has no entry for policy metric {metric!r}")


def _not_applicable_counts(candidate: RunResults) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scored in candidate.values:
        for value in scored.values:
            if value.status is MetricStatus.NOT_APPLICABLE:
                counts[value.metric] = counts.get(value.metric, 0) + 1
    return dict(sorted(counts.items()))


def _top_failing(
    tables: Mapping[str, PairedTable], decisions: list[SliceDecision]
) -> tuple[CaseId, ...]:
    worst: dict[str, float] = {}
    for d in decisions:
        if d.dimension != OVERALL or d.status not in _FAILING or d.metric not in tables:
            continue
        table = tables[d.metric]
        members = slice_members(table, OVERALL, OVERALL)
        for case_id, diff in zip(
            np.asarray(table.case_ids)[members], table.diffs[members], strict=True
        ):
            worst[str(case_id)] = min(worst.get(str(case_id), 0.0), float(diff))
    ranked = sorted((diff, case_id) for case_id, diff in worst.items() if diff < 0)
    return tuple(CaseId(case_id) for _, case_id in ranked[:_TOP_CASES])


def _status(hard_fails: int, rows: list[SliceDecision], candidate: RunResults) -> GateStatus:
    gated = [r.status for r in rows if r.gated]
    if hard_fails or GateStatus.FAIL in gated:
        return GateStatus.FAIL
    if GateStatus.WARN in gated or candidate.manifest.counts.get("unsupported_config", 0) > 0:
        return GateStatus.WARN
    return GateStatus.PASS


def _notable_order(d: SliceDecision) -> tuple[bool, float, str, str, str]:
    mean_diff = d.result.mean_diff if d.result else 0.0
    return (not d.notable, mean_diff, d.metric, d.dimension, d.value)


def _collect_pairs(
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    directions: Mapping[str, bool],
    informational: Mapping[str, str],
) -> tuple[list[Pair], dict[str, PairedTable]]:
    pairs: list[Pair] = []
    tables: dict[str, PairedTable] = {}
    for metric in sorted(policy.metrics):
        max_drop = policy.metrics[metric].max_drop
        if max_drop is None:
            continue
        table = pair_runs(baseline, candidate, metric, higher_is_better=directions[metric])
        tables[metric] = table
        reason = informational_reason(table, metric, informational)
        pairs.extend(metric_pairs(table, policy, max_drop, reason))
    return pairs, tables


def evaluate_gate(
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    rng: np.random.Generator,
    *,
    directions: Mapping[str, bool],
    informational: Mapping[str, str] = _NO_INFORMATIONAL,
) -> GateReport:
    """Turn a baseline and a candidate run into a complete ``GateReport``.

    See the module docstring for the algorithm. Hard fails come first, then absolute checks, then
    paired decisions with one Holm family for the whole run; all other slices are informational.

    Args:
        baseline: Baseline run.
        candidate: Candidate run.
        policy: Gate policy.
        rng: Randomness of all bootstraps (used sequentially, in the contractual order).
        directions: metric -> ``higher_is_better`` (from ``MetricRegistry.directions()``).
        informational: metric -> reason, from the pipeline (tier 1, uncalibrated judge, ...).

    Returns:
        The report (``no_baseline`` is always ``False`` here).

    Raises:
        GateInputError: Fingerprint mismatch, an incomplete run, a baseline ``error_rate`` above
            ``max_error_rate``, a policy metric without a direction, or a non-binary value of an
            absolute-check metric.
    """
    _validate(baseline, candidate, policy, directions)
    hard_fails = find_hard_fails(candidate, policy.hard_fail)
    pairs, tables = _collect_pairs(baseline, candidate, policy, directions, informational)
    bootstrap_pairs(pairs, policy, rng)
    rows = build_decisions(pairs, policy)
    decisions = [d for d in rows if d.gated]
    notable = sorted((d for d in rows if not d.gated), key=_notable_order)
    paired_overall = {d.metric: d.status for d in decisions if d.dimension == OVERALL}
    absolute = absolute_checks(baseline, candidate, policy, informational, paired_overall)
    return GateReport(
        schema_version="1",
        status=_status(len(hard_fails), [*decisions, *absolute], candidate),
        baseline_run_id=baseline.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        eval_fingerprint=candidate.manifest.eval_fingerprint,
        hard_fails=hard_fails,
        decisions=tuple(decisions),
        absolute_checks=absolute,
        notable_slices=tuple(notable),
        likely_cause=likely_cause([*decisions, *absolute]),
        top_failing_cases=_top_failing(tables, decisions),
        not_applicable_counts=_not_applicable_counts(candidate),
        no_baseline=False,
    )
