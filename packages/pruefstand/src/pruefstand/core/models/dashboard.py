"""Dashboard models (interfaces §10.1): the files ``pruefstand export-dashboard`` writes.

Every field is copied from ``run.json`` / ``gate.json`` / the run's results, never computed
(CLAUDE.md §4). T1.9 owns ``LabelsDocument``; T8.1 owns the others and the size-cap constants.
"""

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.enums import Category, GateStatus, Lang, MetricStatus
from pruefstand.core.ids import CaseId, ChunkId, RunId, TenantId
from pruefstand.core.models.gate import CauseCode

MAX_INDEX_RUNS: Final = 200
"""Newest runs listed in ``runs/index.json`` of the dashboard-data repo (D259, D300)."""
MAX_CASE_RUNS: Final = 20
"""Newest runs that keep ``cases/<run_id>/`` shards and ``report.html`` there (D259, D300)."""
MAX_SHARD_CASES: Final = 500
"""Cases per ``cases/<run_id>/<shard>.json`` (ui-spec §2.3)."""


class RunIndexEntry(BaseModel):
    """One row of ``runs/index.json``, copied from ``run.json`` and ``gate.json``.

    Attributes:
        status: Gate status; ``None`` when the run has no ``gate.json``.
        baseline_run_id: ``None`` without ``gate.json`` or without a baseline.
        no_baseline: ``GateReport.no_baseline`` (``False`` without ``gate.json``).
        block: ``RunManifest.block`` (nightly block k, UI13-19).
        judged_subset: ``RunManifest.judged_subset`` (UI13-19).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    created_at: datetime
    git_ref: str | None
    git_sha: str | None
    pr_number: int | None
    n_cases: int
    duration_s: float
    cost_usd: float
    complete: bool
    stop_reason: str
    stack: Literal["live", "a40"]
    workload: Literal["pr", "nightly", "bench"]
    judge_mode: Literal["github", "local", "skipped"]
    judge_fallback: bool
    judge_degraded: bool
    judge_drift: bool
    status: GateStatus | None
    baseline_run_id: RunId | None
    no_baseline: bool = False
    block: int | None = None
    judged_subset: bool = False


class DashboardRunIndex(BaseModel):
    """``runs/index.json``: at most ``MAX_INDEX_RUNS`` runs, newest first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    runs: tuple[RunIndexEntry, ...]


class DashboardSliceRow(BaseModel):
    """One row per ``SliceDecision`` of ``gate.json`` (ui-spec §11.1), copied, never computed.

    ``kind``: ``absolute_checks`` give ``absolute``; ``notable_slices`` and every entry with an
    ``informational_reason`` give ``informational``; the other decisions give ``decision``. The
    CI fields are ``None`` when the decision has no bootstrap ``result``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    dimension: str
    value: str
    status: GateStatus
    gated: bool
    notable: bool
    kind: Literal["decision", "absolute", "informational"]
    baseline_mean: float
    candidate_mean: float
    mean_diff: float | None
    ci_low: float | None
    ci_high: float | None
    mde: float | None
    max_drop: float | None
    max_value: float | None
    n_clusters: int | None
    informational_reason: str | None


class DashboardSlices(BaseModel):
    """``runs/<run_id>/slices.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    run_id: RunId
    rows: tuple[DashboardSliceRow, ...]


class DashboardCase(BaseModel):
    """Per-case fields of the cases list and the case page (sanitised, no chunk text).

    Attributes:
        citations: From the response, canaries masked.
        retrieved_chunk_tenant_ids: Parallel to ``retrieved_chunk_ids``; ``""`` when the target
            did not report a chunk's tenant.
        error: The error class only (``TimeoutError``, ``TargetError``, ...), never its message.
        failing: In ``GateReport.top_failing_cases`` or named by a hard fail.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: CaseId
    tenant: TenantId
    lang: Lang
    category: Category
    perturbation: str | None
    question: str
    answer: str | None
    expect_refusal: bool
    refused: bool | None
    citations: tuple[str, ...]
    retrieved_chunk_ids: tuple[ChunkId, ...]
    retrieved_chunk_tenant_ids: tuple[TenantId, ...]
    error: str | None
    metric_values: dict[str, float | None]
    metric_status: dict[str, MetricStatus]
    failing: bool


class DashboardCases(BaseModel):
    """``cases/<run_id>/<shard>.json``: at most ``MAX_SHARD_CASES`` cases, shard 0 first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    run_id: RunId
    shard: int
    n_shards: int
    cases: tuple[DashboardCase, ...]


class LabelsDocument(BaseModel):
    """``labels.json``: the en labels the PR comment, the HTML report and the dashboard share.

    Built by ``pruefstand.report.labels.labels_document()`` and copied to ``data/labels.json`` by
    ``export-dashboard``, so the dashboard never re-types a label (ui-spec §10.4.3).

    Attributes:
        metrics: Metric code to label (every ``KNOWN_METRICS`` name and ``evidence_recall``).
        causes: Cause code to message (``CAUSE_MESSAGES``).
        hard_fail_rules: Hard-fail rule code to label (R12 UI12-15, D273).
        informational_reasons: Every ``informational_reason`` code of interfaces §9 to its label.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    metrics: dict[str, str]
    causes: dict[CauseCode, str]
    hard_fail_rules: dict[str, str]
    informational_reasons: dict[str, str]
