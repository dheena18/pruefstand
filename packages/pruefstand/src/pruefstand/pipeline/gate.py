"""``run_gate``: two stored runs in, ``gate.json`` out (T1.10 S3, S4b)."""

import re
from pathlib import Path

import numpy as np

from pruefstand.core.config import GatePolicy, PruefstandConfig
from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import GateStatus, Split
from pruefstand.core.errors import GateInputError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.logging import get_logger
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest, RunResults
from pruefstand.core.protocols import BaselineStore
from pruefstand.gate.hard_fail import find_hard_fails
from pruefstand.gate.policy import evaluate_gate
from pruefstand.judges.calibration import judges_uncalibrated
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.report.json_report import write_gate_json
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baseline_index import validate_ref
from pruefstand.store.factory import build_baseline_store

_log = get_logger(__name__)
GATE_FILE = "gate.json"


def _tier_one(policy: GatePolicy) -> dict[str, str]:
    """Tier 1 decides on hard fails and the ``error_rate`` absolute check only (X5.6, X3.11)."""
    mapping: dict[str, str] = {}
    for metric, rule in policy.metrics.items():
        if metric in JUDGED_METRICS:
            mapping[metric] = "tier1_judged"
        elif metric == "injection_success":
            mapping[metric] = "tier1_injection_reported"
        elif rule.max_drop is not None:
            mapping[metric] = "tier1_deterministic_only"
    return mapping


def _judge_reason(
    baseline: RunManifest, candidate: RunManifest, *, uncalibrated: bool
) -> str | None:
    """First matching reason why judged metrics do not gate (tier 2).

    Candidate truncation is never a reason (X3.9, D815): the candidate controls its answer, so a
    truncated input counts against it in the pairing instead of switching the metric off.
    """
    checks = (
        (baseline.judge_fallback or candidate.judge_fallback, "judge_fallback"),  # Y4.4
        ("skipped" in (baseline.judge_mode, candidate.judge_mode), "judge_skipped"),
        (baseline.judge_degraded or candidate.judge_degraded, "judge_degraded"),
        (baseline.judge_drift or candidate.judge_drift, "judge_drift"),
        (uncalibrated, "judge_uncalibrated"),  # T5.4 found no passing judge (W3.8)
    )
    return next((reason for hit, reason in checks if hit), None)


def informational_mapping(
    baseline: RunManifest,
    candidate: RunManifest,
    policy: GatePolicy,
    *,
    uncalibrated: bool = False,
) -> dict[str, str]:
    """Metrics the gate must treat as informational, with the reason (interfaces §9).

    First match wins: (1) tier 1 (``stack == "live"``): judged metrics ``tier1_judged``,
    ``injection_success`` ``tier1_injection_reported``, every other metric with ``max_drop``
    ``tier1_deterministic_only``; (2) tier 2: judged metrics ``judge_fallback`` /
    ``judge_degraded`` /
    ``judge_drift`` / ``judge_uncalibrated`` (never ``judge_truncated``: a truncated candidate
    input is worst-filled by the pairing, D815); (3)
    ``refusal_correct`` unless the run is the nightly on ``full``
    (``refusal_outside_nightly_full``). ``false_refusal`` is gated like any answerable
    metric. Only metrics of ``policy`` appear.

    Args:
        baseline: Baseline manifest.
        candidate: Candidate manifest (stack, workload and splits come from here).
        policy: The gate policy.
        uncalibrated: ``judges/data/calibration_status.yaml`` says no judge passed (T5.4).

    Returns:
        Metric name to reason; metrics that are gated normally are absent.
    """
    if candidate.stack == "live":
        return _tier_one(policy)
    mapping: dict[str, str] = {}
    judged = {m for m in policy.metrics if m in JUDGED_METRICS}
    reason = _judge_reason(baseline, candidate, uncalibrated=uncalibrated)
    if reason is not None:
        mapping.update(dict.fromkeys(judged, reason))
    nightly_full = candidate.workload == "nightly" and Split.FULL in candidate.splits
    if "refusal_correct" in policy.metrics and not nightly_full:
        mapping["refusal_correct"] = "refusal_outside_nightly_full"
    return mapping


def _read(path: Path) -> RunResults:
    return ArtifactStore(path.parent).read_run(path).results


def _without_baseline(candidate: RunResults, policy: GatePolicy) -> GateReport:
    """The report for a candidate that has no baseline (interfaces §15, R9 X5.5).

    A hard fail still fails: a leak does not need a baseline to be a leak. An incomplete
    candidate (aborted, budget exhausted, corpus mismatch) is refused like in ``evaluate_gate``.

    Raises:
        GateInputError: The candidate run is not complete.
    """
    if not candidate.manifest.complete:
        msg = (
            f"the candidate run is not complete (stop_reason={candidate.manifest.stop_reason}); "
            "the gate refuses incomplete runs"
        )
        raise GateInputError(msg)
    hard_fails = find_hard_fails(candidate, policy.hard_fail)
    status = GateStatus.FAIL if hard_fails else GateStatus.INSUFFICIENT_DATA
    return GateReport(
        schema_version="1",
        status=status,
        baseline_run_id=None,
        candidate_run_id=candidate.manifest.run_id,
        eval_fingerprint=candidate.manifest.eval_fingerprint,
        hard_fails=hard_fails,
        decisions=(),
        absolute_checks=(),
        notable_slices=(),
        likely_cause=None,
        top_failing_cases=(),
        no_baseline=True,
    )


def _require_same_stack(base: RunResults | None, cand: RunResults) -> None:
    """Tier 1 and tier 2 results are never compared (the stack is not part of the fingerprint).

    Raises:
        GateInputError: The two runs ran on different stacks.
    """
    if base is not None and base.manifest.stack != cand.manifest.stack:
        msg = (
            f"the baseline ran on stack {base.manifest.stack!r}, the candidate on "
            f"{cand.manifest.stack!r}: tier 1 and tier 2 results are never compared"
        )
        raise GateInputError(msg)


def _decide(cand: RunResults, base: RunResults | None, cfg: PruefstandConfig) -> GateReport:
    """The report for two verified runs, or for a candidate without baseline."""
    if stable_hash(cfg) != cand.manifest.config_hash:
        _log.warning(
            "gate_config_hash_differs",
            run_id=cand.manifest.run_id,
            note="the gate policy of this config is not the one the run was made with",
        )
    from_base = cand.manifest.counts.get("cached_from_base", 0)
    if from_base > 0 and from_base >= cand.manifest.n_cases:
        leaked = _without_baseline(cand, cfg.gate)  # a leak in cached answers is still a FAIL
        if leaked.hard_fails:
            return leaked
        msg = (
            f"all {from_base} answers of the candidate came from the baseline cache: "
            "the candidate never ran, so there is nothing to gate"
        )
        raise GateInputError(msg)
    if base is None:
        return _without_baseline(cand, cfg.gate)
    report = evaluate_gate(
        base,
        cand,
        cfg.gate,
        np.random.default_rng(cfg.seed),
        directions=MetricRegistry.full().directions(),
        informational=informational_mapping(
            base.manifest,
            cand.manifest,
            cfg.gate,
            uncalibrated=judges_uncalibrated(),
        ),
    )
    if from_base > 0 and report.status is GateStatus.PASS:
        _log.warning("gate_answers_from_base_cache", count=from_base)
        return report.model_copy(update={"status": GateStatus.WARN})
    return report


def _finish(report: GateReport, candidate: Path) -> GateReport:
    write_gate_json(report, candidate / GATE_FILE)
    _log.info("gate_decided", status=report.status.value, no_baseline=report.no_baseline)
    return report


def run_gate(candidate: Path, baseline: Path | None, cfg: PruefstandConfig) -> GateReport:
    """Compare a candidate run with a baseline run and write ``gate.json`` into the candidate.

    The directions of the metrics come from ``MetricRegistry.full().directions()``, the
    randomness from ``numpy.random.default_rng(cfg.seed)``, so equal inputs give an equal report.
    Without a baseline the report says ``no_baseline`` (``INSUFFICIENT_DATA``, or ``FAIL`` when the
    candidate has a hard fail). A config whose hash differs from the one in ``run.json`` is
    logged as a warning (the policy may not be the one the run was made with).

    Args:
        candidate: Candidate run directory.
        baseline: Baseline run directory, or None.
        cfg: Configuration; ``gate`` is the policy, ``seed`` seeds the bootstraps.

    Returns:
        The report that was written.

    Raises:
        StoreError: A run directory is missing or invalid.
        GateInputError: The runs cannot be compared (fingerprint, stack, incomplete run, unknown
            metric direction, ...).
    """
    cand = _read(candidate)
    base = None if baseline is None else _read(baseline)
    _require_same_stack(base, cand)
    return _finish(_decide(cand, base, cfg), candidate)


_REF_BLOCK = re.compile(r"(?:nightly|release)-b([0-2])")


def gate_from_store(
    candidate: Path, cfg: PruefstandConfig, *, ref: str = "main", store: BaselineStore | None = None
) -> GateReport:
    """Gate ``candidate`` against the baseline of its fingerprint and ``ref`` in the store.

    PR runs use ``main``; the nightly gate ``nightly-b<k>`` and the drift job ``release-b<k>``
    with ``k`` the candidate's block. Without a baseline the report says ``no_baseline`` and the
    command still succeeds (the executor turns it into a failure on a gated PR, D103). The
    baseline must come from the same stack as the candidate.

    Args:
        candidate: Candidate run directory.
        cfg: Configuration (gate policy, seed, ``baseline_store``).
        ref: One of the baseline refs.
        store: The baseline store; default ``build_baseline_store(cfg.baseline_store)``.

    Returns:
        The report that was written into the candidate directory.

    Raises:
        StoreError: Unknown ref, an invalid candidate or an invalid baseline in the store.
        GateInputError: ``ref`` names another block than the candidate's, the baseline is of
            another stack, or the runs cannot be compared.
    """
    validate_ref(ref)
    cand = _read(candidate)
    match = _REF_BLOCK.fullmatch(ref)
    if match and cand.manifest.block != int(match.group(1)):
        msg = (
            f"--ref {ref} needs a candidate with block {match.group(1)}; "
            f"run {cand.manifest.run_id} has block {cand.manifest.block}"
        )
        raise GateInputError(msg)
    found = (store or build_baseline_store(cfg.baseline_store)).get(
        cand.manifest.eval_fingerprint, ref
    )
    base = None if found is None else found.results
    _require_same_stack(base, cand)
    return _finish(_decide(cand, base, cfg), candidate)
