"""``build_evidence_record``: the release evidence record from a gate report and run manifests."""

from pruefstand.core.models.evidence import (
    EvidenceMetric,
    EvidenceRecord,
    EvidenceRun,
    EvidenceSecurity,
)
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.run import RunManifest
from pruefstand.report.tables import Source, assign_table

_LEAK_METRICS = ("canary_leak", "tenant_leak", "system_prompt_leak")


def _run(manifest: RunManifest) -> EvidenceRun:
    return EvidenceRun(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        git_sha=manifest.git_sha,
        git_ref=manifest.git_ref,
        pr_number=manifest.pr_number,
        pruefstand_version=manifest.pruefstand_version,
        eval_fingerprint=manifest.eval_fingerprint,
        target_fingerprint=manifest.target_fingerprint,
        config_hash=manifest.config_hash,
        complete=manifest.complete,
        stop_reason=manifest.stop_reason,
    )


def _metric(decision: SliceDecision, source: Source) -> EvidenceMetric:
    res = decision.result
    return EvidenceMetric(
        metric=decision.metric,
        dimension=decision.dimension,
        value=decision.value,
        table=assign_table(decision, source).value,
        status=decision.status,
        informational_reason=decision.informational_reason,
        baseline_mean=decision.baseline_mean,
        candidate_mean=decision.candidate_mean,
        mean_diff=None if res is None else res.mean_diff,
        ci_low=None if res is None else res.ci_low,
        ci_high=None if res is None else res.ci_high,
        confidence=None if res is None else res.confidence,
        p_adjusted=decision.p_adjusted,
        mde=decision.mde,
        max_drop=decision.max_drop,
        max_value=decision.max_value,
        n_clusters=decision.n_clusters,
    )


def _results(report: GateReport) -> tuple[EvidenceMetric, ...]:
    pairs: tuple[tuple[Source, tuple[SliceDecision, ...]], ...] = (
        ("decisions", report.decisions),
        ("absolute_checks", report.absolute_checks),
        ("notable_slices", report.notable_slices),
    )
    return tuple(_metric(d, source) for source, rows in pairs for d in rows)


def _security(report: GateReport) -> EvidenceSecurity:
    leaks = dict.fromkeys(_LEAK_METRICS, 0)
    unverifiable = dict.fromkeys(_LEAK_METRICS, 0)
    for finding in report.hard_fails:
        counts = leaks if finding.rule == "hard_fail" else unverifiable
        counts[finding.metric] = counts.get(finding.metric, 0) + 1
    injection = next(
        (
            d.candidate_mean
            for d in (*report.absolute_checks, *report.decisions, *report.notable_slices)
            if d.metric == "injection_success" and d.dimension == "overall"
        ),
        None,
    )
    return EvidenceSecurity(
        hard_fail_count=len(report.hard_fails),
        hard_fails=report.hard_fails,
        leak_metrics=leaks,
        unverifiable=unverifiable,
        injection_success=injection,
    )


def build_evidence_record(
    report: GateReport, base: RunManifest | None, cand: RunManifest, reviewer: str | None
) -> EvidenceRecord:
    """Build the release evidence record of one gate decision.

    Only manifests are given, so the artefact hashes (``run.json`` of both runs, ``gate.json``) and
    the ``thresholds`` stay empty; ``pruefstand report --format evidence`` fills them with
    ``model_copy(update=...)`` from the files and the loaded config.

    Args:
        report: The gate report of the candidate.
        base: Baseline manifest; ``None`` when there is no baseline or it is not available (the
            baseline fields are then ``None``; ``baseline_run_id`` keeps the id of the report).
        cand: Candidate manifest.
        reviewer: Name of the person who reviewed the decision, if any.

    Returns:
        The record; it validates against ``schemas/evidence_record.schema.json``.
    """
    target = cand.target
    return EvidenceRecord(
        created_at=cand.created_at,
        gate_status=report.status,
        no_baseline=report.no_baseline,
        reviewer=reviewer,
        dataset_name=cand.dataset_name,
        dataset_version=cand.dataset_version,
        corpus_version=None if target is None else target.corpus_version,
        splits=tuple(s.value for s in cand.splits),
        n_cases=cand.n_cases,
        stack=cand.stack,
        workload=cand.workload,
        eval_fingerprint=cand.eval_fingerprint,
        target_fingerprint=cand.target_fingerprint,
        config_hash=cand.config_hash,
        seed=cand.seed,
        candidate=_run(cand),
        baseline=None if base is None else _run(base),
        baseline_run_id=report.baseline_run_id,
        model_ids={} if target is None else dict(target.models),
        judge_mode=cand.judge_mode,
        judge_models=dict(cand.judge_models),
        judge_prompt_versions=dict(cand.judge_prompt_versions),
        metric_versions=dict(cand.metric_versions),
        likely_cause=report.likely_cause,
        not_applicable_counts=dict(report.not_applicable_counts),
        n_unmatched=dict(report.n_unmatched),
        n_excluded=dict(report.n_excluded),
        results=_results(report),
        security=_security(report),
    )
