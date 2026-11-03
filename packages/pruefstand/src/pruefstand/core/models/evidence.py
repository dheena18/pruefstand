"""The release evidence record (interfaces §10, T6.4): re-run and audit a gate decision."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import HardFailFinding

STATEMENT = (
    "This record supports documentation for accuracy, robustness and record-keeping. "
    "It is not a compliance certificate."
)


class EvidenceRun(BaseModel):
    """One of the two runs behind a gate decision.

    ``run_json_sha256`` is empty (``None``) when the builder only saw the manifest; the CLI fills
    it from the file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    created_at: datetime
    git_sha: str | None
    git_ref: str | None
    pr_number: int | None
    pruefstand_version: str
    eval_fingerprint: str
    target_fingerprint: str
    config_hash: str
    complete: bool
    stop_reason: Literal["completed", "budget_exceeded", "aborted"]
    run_json_sha256: str | None = None


class EvidenceMetric(BaseModel):
    """The result of one (metric, slice) pair or absolute check, copied from ``gate.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    metric: str
    dimension: str
    value: str
    table: str  # "gated" | "informational" | "notable" (ui-spec §11.1)
    status: GateStatus
    informational_reason: str | None
    baseline_mean: float
    candidate_mean: float
    mean_diff: float | None
    ci_low: float | None
    ci_high: float | None
    confidence: float | None
    p_adjusted: float | None
    mde: float | None
    max_drop: float | None
    max_value: float | None
    n_clusters: int | None


class EvidenceSecurity(BaseModel):
    """Security results: the (redacted) hard fails and the injection success rate."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    hard_fail_count: int
    hard_fails: tuple[HardFailFinding, ...]
    leak_metrics: dict[str, int]
    unverifiable: dict[str, int]
    injection_success: float | None


class EvidenceRecord(BaseModel):
    """Release evidence record (``evidence.json``, ``pruefstand report --format evidence``).

    ``created_at`` is the creation time of the candidate run (the builder is pure and reads no
    clock). ``baseline`` is ``None`` when there is no baseline or its manifest is not available;
    ``baseline_run_id`` keeps the id from ``gate.json`` in that case. ``thresholds`` is filled by
    the CLI from the loaded config (neither ``GateReport`` nor ``RunManifest`` carries the policy).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1"] = "1"
    statement: str = STATEMENT
    created_at: datetime
    gate_status: GateStatus
    no_baseline: bool
    reviewer: str | None
    dataset_name: str
    dataset_version: str
    corpus_version: str | None
    splits: tuple[str, ...]
    n_cases: int
    stack: Literal["live", "a40"]
    workload: Literal["pr", "nightly", "bench"]
    eval_fingerprint: str
    target_fingerprint: str
    config_hash: str
    seed: int
    candidate: EvidenceRun
    baseline: EvidenceRun | None
    baseline_run_id: str | None
    gate_json_sha256: str | None = None
    model_ids: dict[str, str]
    judge_mode: Literal["github", "local", "skipped"]
    judge_models: dict[str, str]
    judge_prompt_versions: dict[str, str]
    metric_versions: dict[str, str]
    thresholds: GatePolicy | None = None
    likely_cause: str | None
    not_applicable_counts: dict[str, int]
    n_unmatched: dict[str, int]
    n_excluded: dict[str, int]
    results: tuple[EvidenceMetric, ...]
    security: EvidenceSecurity
