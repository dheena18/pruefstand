"""Run artefact models (interfaces §2 and §8): manifest, scored cases and the on-disk run."""

from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from pruefstand.core.enums import Split
from pruefstand.core.ids import RunId
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import CaseRecord, TargetInfo
from pruefstand.core.models.testcase import TestCase


class CostSummary(BaseModel):
    """Cost of a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    usd: float
    prompt_tokens: int
    completion_tokens: int
    gpu_seconds: float
    llm_calls: int


class RunManifest(BaseModel):
    """``run.json``: everything needed to interpret a run.

    ``counts`` keys (single owner = the runner): ``ok``, ``error``, ``cached``, ``not_applicable``,
    ``judge_error``, ``judge_skipped`` (details reason ``judge_quota`` | ``judge_cap``),
    ``judge_truncated``, ``metric_truncated`` (deterministic values with ``details.truncated``),
    ``think_stripped``, ``corpus_mismatch``, ``retrieve`` (``robust_pr``
    cases sent to ``/v1/retrieve``, R11 D218), ``retrieve_fallback`` (target without
    ``/v1/retrieve``), and ``model_reloads`` / ``upstream_errors`` (R12 N6.4: ``llm-proxy``
    ``/health`` differences over the run, written by the T6.2a executor; absent in tier 1 and in
    local runs). An infra failure is the ``infra_error`` field, never a count.

    ``infra_error`` is ``"<kind>: <detail>"`` (kind ``ollama_down`` | ``tunnel_lost`` |
    ``data_root_unavailable`` | ``proxy_upstream`` | ``model_reload`` | ``window_exceeded``).

    Run-time flags (``judge_drift``, ``judge_degraded``, ``judge_fallback``) never change
    ``eval_fingerprint``; ``block``, ``judged_subset`` and a ``stratum`` other than ``"all"`` do.

    ``artifact_sha256`` is set by ``ArtifactStore.write_run`` (T1.8): file name -> SHA-256 of
    ``results.parquet``, ``responses.jsonl`` and ``scored.jsonl``. Readers must stream-hash a file
    and compare *before* they parse it (a hostile parquet footer can abort a parser); the runner
    leaves it empty.

    Raises:
        ValidationError: ``complete`` differs from ``stop_reason == "completed"``, or
            ``infra_error`` is set with a ``stop_reason`` other than ``"aborted"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    run_id: RunId
    created_at: datetime
    pruefstand_version: str
    git_sha: str | None
    git_ref: str | None
    pr_number: int | None
    target: TargetInfo | None
    target_fingerprint: str
    eval_fingerprint: str
    dataset_name: str
    dataset_version: str
    splits: tuple[Split, ...]
    n_cases: int
    block: int | None = None
    judged_subset: bool = False
    stratum: Literal["all", "refusal", "blocks"] = "all"
    config_hash: str
    judge_models: dict[str, str]
    judge_prompt_versions: dict[str, str]
    judge_serving: dict[str, str] = {}
    judge_epoch: int = 0
    metric_versions: dict[str, str]
    seed: int
    cost: CostSummary
    duration_s: float
    counts: dict[str, int]
    complete: bool
    stop_reason: Literal["completed", "budget_exceeded", "aborted"]
    infra_error: str | None = None
    stack: Literal["live", "a40"]
    workload: Literal["pr", "nightly", "bench"]
    judge_mode: Literal["github", "local", "skipped"]
    judge_fallback: bool = False
    judge_degraded: bool = False
    judge_drift: bool = False
    judged_cases: int = 0
    artifact_sha256: dict[str, str] = {}

    @model_validator(mode="after")
    def _check_stop_state(self) -> Self:
        if self.complete != (self.stop_reason == "completed"):
            msg = f"complete={self.complete} contradicts stop_reason={self.stop_reason!r}"
            raise ValueError(msg)
        if self.infra_error is not None and self.stop_reason != "aborted":
            msg = "infra_error requires stop_reason 'aborted'"
            raise ValueError(msg)
        return self


class ScoredCase(BaseModel):
    """A test case with all its metric values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: TestCase
    values: tuple[MetricValue, ...]


class RunResults(BaseModel):
    """The content of a run directory, parsed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: RunManifest
    records: tuple[CaseRecord, ...]
    values: tuple[ScoredCase, ...]


class RunArtifacts(BaseModel):
    """A run as stored on disk (``runs/<run_id>/``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: RunResults
    root: Path
