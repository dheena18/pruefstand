"""Gate models (interfaces §9): scores, bootstrap results, decisions, report and cause codes."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.enums import GateStatus
from pruefstand.core.ids import CaseId, RunId


class ScoreTable(BaseModel):
    """One metric of one run, one value per case, aligned by ``case_id`` when paired.

    ``slices`` maps a dimension (``category``, ``perturbation``, ``tenant``, ``lang``, ``tags``)
    to the slice value of each case.

    Raises:
        ValidationError: ``case_ids``, ``cluster_ids``, ``values`` and every ``slices`` value
            tuple do not all have the same length, a ``case_id`` is duplicated, or a value is
            NaN or infinite.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    metric: str
    higher_is_better: bool
    case_ids: tuple[CaseId, ...]
    cluster_ids: tuple[str, ...]
    values: tuple[float, ...]
    slices: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def _aligned(self) -> Self:
        n = len(self.case_ids)
        if len(set(self.case_ids)) != n:
            msg = "duplicate case_ids"
            raise ValueError(msg)
        if len(self.cluster_ids) != n or len(self.values) != n:
            msg = "case_ids, cluster_ids and values must have the same length"
            raise ValueError(msg)
        for name, column in self.slices.items():
            if len(column) != n:
                msg = f"slice {name!r} has {len(column)} values for {n} cases"
                raise ValueError(msg)
        return self


class BootstrapResult(BaseModel):
    """Result of a paired cluster bootstrap (negative ``mean_diff`` = candidate worse).

    ``p_value`` is one-sided for H0 "no drop" (mean difference >= 0). ``ci_low``/``ci_high`` are the
    display interval at ``confidence``; ``method`` says where ``p_value`` came from.

    Raises:
        ValidationError: A float is not finite, ``p_value`` is outside [0, 1],
            ``n_clusters`` exceeds ``n_cases`` or a count is below 1.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    mean_diff: float
    ci_low: float
    ci_high: float
    p_value: float = Field(ge=0.0, le=1.0)
    method: Literal["bootstrap", "sign_test"]
    se: float = Field(ge=0.0)
    n_cases: int = Field(ge=1)
    n_clusters: int = Field(ge=1)
    n_resamples: int = Field(ge=1)
    confidence: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _clusters_le_cases(self) -> Self:
        if self.n_clusters > self.n_cases:
            msg = "n_clusters cannot exceed n_cases"
            raise ValueError(msg)
        return self


CauseCode = Literal[
    "retrieval", "generation", "citation_format", "language", "refusal_policy", "errors", "mixed"
]

# SPEC §7.4, verbatim. Lives here because ``report`` may not import ``gate``. For ``mixed`` the
# renderer replaces ``<codes>`` with the matched codes.
CAUSE_MESSAGES: dict[CauseCode, str] = {
    "errors": "Target errors or timeouts",
    "retrieval": "Retrieval (chunking, embeddings, top-k, reranker, filter, analyzer)",
    "generation": "Generation (model or prompt)",
    "citation_format": "Prompt / citation formatting",
    "language": "Prompt: answer language",
    "refusal_policy": "Refusal policy in prompt",
    "mixed": "Several causes: <codes>",
}


class HardFailFinding(BaseModel):
    """One hard fail (no statistics): a leak on a case, or a leak check that could not run.

    ``rule`` is ``"hard_fail"`` (the metric is 1 on the case) or ``"hard_fail_unverifiable"``
    (the metric is ``error``/``not_applicable`` on a case of a target that declares chunk
    support, so the leak could not be ruled out). ``evidence`` is redacted: at most 200
    characters, canary tokens masked, never chunk text.

    Raises:
        ValidationError: ``evidence`` is longer than 200 characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    case_id: CaseId
    metric: str
    evidence: str = Field(max_length=200)


class SliceDecision(BaseModel):
    """The decision on one (metric, slice) pair or one absolute check (interfaces §9).

    ``max_drop`` (paired rows) and ``max_value`` (absolute rows) are copied from the policy so
    renderers never re-read the config. ``notable`` is set for informational rows only.

    Raises:
        ValidationError: ``informational_reason`` is set although ``gated`` is true (R9 X5.4), or a
            float is not finite.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    metric: str
    dimension: str
    value: str
    status: GateStatus
    gated: bool
    notable: bool = False
    baseline_mean: float
    candidate_mean: float
    result: BootstrapResult | None
    p_adjusted: float | None
    mde: float | None
    max_drop: float | None = None
    max_value: float | None = None
    n_clusters: int | None = None
    informational_reason: str | None = None

    @model_validator(mode="after")
    def _reason_means_not_gated(self) -> Self:
        if self.informational_reason is not None and self.gated:
            msg = "a decision with an informational_reason must have gated=False"
            raise ValueError(msg)
        return self


class GateReport(BaseModel):
    """The gate's answer for one candidate run (``gate.json``).

    ``baseline_run_id`` is ``None`` exactly when ``no_baseline`` is true. ``n_unmatched`` and
    ``n_excluded`` map a paired metric to the cases dropped from its pairing (only metrics with
    a non-zero count): in one run only, and excluded (baseline not ``ok``, judge error).

    Raises:
        ValidationError: ``baseline_run_id is None`` differs from ``no_baseline``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    status: GateStatus
    baseline_run_id: RunId | None
    candidate_run_id: RunId
    eval_fingerprint: str
    hard_fails: tuple[HardFailFinding, ...]
    decisions: tuple[SliceDecision, ...]
    absolute_checks: tuple[SliceDecision, ...]
    notable_slices: tuple[SliceDecision, ...]
    likely_cause: CauseCode | None
    top_failing_cases: tuple[CaseId, ...]
    not_applicable_counts: dict[str, int] = {}
    no_baseline: bool = False
    n_unmatched: dict[str, int] = {}
    n_excluded: dict[str, int] = {}

    @model_validator(mode="after")
    def _baseline_iff_not_missing(self) -> Self:
        if (self.baseline_run_id is None) != self.no_baseline:
            msg = "baseline_run_id is None exactly when no_baseline is true"
            raise ValueError(msg)
        return self
