"""Row builders of ``export-dashboard``: index entry, slice rows, case shards (ui-spec §2.3, §11.1).

Everything is copied from ``run.json``, ``gate.json`` and the (already sanitised) results, never
computed. Pure functions; the caller owns all I/O.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pruefstand.core.ids import ChunkId, TenantId
from pruefstand.core.models.dashboard import (
    MAX_SHARD_CASES,
    DashboardCase,
    DashboardCases,
    DashboardSliceRow,
    DashboardSlices,
    RunIndexEntry,
)
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord

_CLASS = re.compile(r"[A-Z][A-Za-z0-9]*(?:Error|Exception|Timeout)\b")
_TIMEOUT = re.compile(r"timeout", re.IGNORECASE)
Kind = Literal["decision", "absolute", "informational"]


def error_class(text: str | None) -> str | None:
    """Reduce a target error text to a class name; the message itself is never kept.

    Args:
        text: ``CaseRecord.error`` (free text from the runner or the target adapter).

    Returns:
        ``None`` for no error; a class-like token found at the start of the text; ``TimeoutError``
        for a timeout text; else ``TargetError``.

    Example:
        >>> error_class(None) is None
        True
        >>> error_class("timeout after 60 s")
        'TimeoutError'
        >>> error_class("ConnectError: boom with CANARY-x")
        'ConnectError'
        >>> error_class("HTTP 500 from the target")
        'TargetError'
    """
    if text is None:
        return None
    found = _CLASS.match(text.strip())
    if found:
        return found.group(0)
    return "TimeoutError" if _TIMEOUT.match(text.strip()) else "TargetError"


def index_entry(manifest: RunManifest, gate: GateReport | None) -> RunIndexEntry:
    """Copy the index fields from a (sanitised) manifest and the gate report, if any."""
    return RunIndexEntry(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        git_ref=manifest.git_ref,
        git_sha=manifest.git_sha,
        pr_number=manifest.pr_number,
        n_cases=manifest.n_cases,
        duration_s=manifest.duration_s,
        cost_usd=manifest.cost.usd,
        complete=manifest.complete,
        stop_reason=manifest.stop_reason,
        stack=manifest.stack,
        workload=manifest.workload,
        judge_mode=manifest.judge_mode,
        judge_fallback=manifest.judge_fallback,
        judge_degraded=manifest.judge_degraded,
        judge_drift=manifest.judge_drift,
        status=None if gate is None else gate.status,
        baseline_run_id=None if gate is None else gate.baseline_run_id,
        no_baseline=False if gate is None else gate.no_baseline,
        block=manifest.block,
        judged_subset=manifest.judged_subset,
    )


def _row(decision: SliceDecision, kind: Kind) -> DashboardSliceRow:
    result = decision.result
    return DashboardSliceRow(
        metric=decision.metric,
        dimension=decision.dimension,
        value=decision.value,
        status=decision.status,
        gated=decision.gated,
        notable=decision.notable,
        kind=kind,
        baseline_mean=decision.baseline_mean,
        candidate_mean=decision.candidate_mean,
        mean_diff=None if result is None else result.mean_diff,
        ci_low=None if result is None else result.ci_low,
        ci_high=None if result is None else result.ci_high,
        mde=decision.mde,
        max_drop=decision.max_drop,
        max_value=decision.max_value,
        n_clusters=decision.n_clusters,
        informational_reason=decision.informational_reason,
    )


def slice_rows(report: GateReport) -> DashboardSlices:
    """One row per ``SliceDecision`` of the report (ui-spec §11.1 ``kind`` rule).

    ``absolute_checks`` are ``absolute``; ``notable_slices`` and every entry with an
    ``informational_reason`` are ``informational``; the other decisions are ``decision``.
    """
    rows: list[DashboardSliceRow] = []
    for decision in report.decisions:
        kind: Kind = "informational" if decision.informational_reason else "decision"
        rows.append(_row(decision, kind))
    rows.extend(_row(d, "absolute") for d in report.absolute_checks)
    rows.extend(_row(d, "informational") for d in report.notable_slices)
    return DashboardSlices(schema_version="1", run_id=report.candidate_run_id, rows=tuple(rows))


def _case(scored: ScoredCase, record: CaseRecord | None, *, failing: bool) -> DashboardCase:
    case = scored.case
    response = None if record is None else record.response
    chunks = () if response is None or response.chunks is None else response.chunks
    return DashboardCase(
        case_id=case.id,
        tenant=case.tenant,
        lang=case.lang,
        category=case.category,
        perturbation=case.perturbation,
        question=case.question,
        answer=None if response is None else response.answer,
        expect_refusal=case.expect_refusal,
        refused=None if response is None else response.refused,
        citations=() if response is None else response.citations,
        retrieved_chunk_ids=tuple(ChunkId(c.chunk_id) for c in chunks),
        retrieved_chunk_tenant_ids=tuple(TenantId(c.tenant_id or "") for c in chunks),
        error=error_class(None if record is None else record.error),
        metric_values={v.metric: v.value for v in scored.values},
        metric_status={v.metric: v.status for v in scored.values},
        failing=failing,
    )


def failing_ids(report: GateReport | None) -> frozenset[str]:
    """Case ids named by ``top_failing_cases`` or by a hard fail."""
    if report is None:
        return frozenset()
    return frozenset(report.top_failing_cases) | {h.case_id for h in report.hard_fails}


def case_shards(
    results: RunResults, failing: Iterable[str], *, size: int = MAX_SHARD_CASES
) -> list[DashboardCases]:
    """Split the cases into shards of at most ``size`` (R4: ``failing`` first, then ``case_id``).

    Shard 0 therefore holds every failing case (while there are at most ``size`` of them). A run
    without cases still has one empty shard 0, so "cases published" is decided by ``0.json``.
    """
    failing_set = frozenset(failing)
    records = {r.case_id: r for r in results.records}
    cases = [
        _case(s, records.get(s.case.id), failing=s.case.id in failing_set) for s in results.values
    ]
    cases.sort(key=lambda c: (not c.failing, c.case_id))
    chunks: Sequence[Sequence[DashboardCase]] = [
        cases[i : i + size] for i in range(0, len(cases), size)
    ] or [[]]
    return [
        DashboardCases(
            schema_version="1",
            run_id=results.manifest.run_id,
            shard=i,
            n_shards=len(chunks),
            cases=tuple(part),
        )
        for i, part in enumerate(chunks)
    ]
