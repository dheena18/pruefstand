"""The part of ``run.json`` the runner knows; the pipeline fills the rest (T1.10)."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

from pruefstand.core.ids import RunId
from pruefstand.core.models.run import CostSummary, RunManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.llm.budget import ChargeTally
from pruefstand.metrics.registry import MetricRegistry

_PLACEHOLDERS: dict[str, Any] = {
    "eval_fingerprint": "",
    "dataset_name": "",
    "dataset_version": "",
    "config_hash": "",
    "judge_models": {},
    "judge_prompt_versions": {},
}
StopReason = Literal["completed", "budget_exceeded", "aborted"]
JUDGE_ERROR_SHARE = 0.05
"""More judge errors than this share of the judged cases set ``judge_degraded`` (D120)."""


def _package_version() -> str:
    try:
        return version("pruefstand")
    except PackageNotFoundError:
        return "0+unknown"


@dataclass(frozen=True)
class RunFacts:
    """What is known when a run starts."""

    run_id: RunId
    created_at: datetime
    cases: tuple[TestCase, ...]
    target_fingerprint: str
    seed: int
    judged_subset: bool
    judges_given: bool


@dataclass(frozen=True)
class RunEnd:
    """What is known when a run ends."""

    cost: ChargeTally
    duration_s: float
    counts: Counter[str]
    stop_reason: StopReason
    judged_cases: int


def build_manifest(facts: RunFacts, end: RunEnd, registry: MetricRegistry) -> RunManifest:
    """Assemble the manifest from what the runner knows.

    Dataset, config and judge fields are placeholders (empty / defaults) until
    ``pipeline.run_eval`` replaces them with ``manifest.model_copy(update=...)``.

    Args:
        facts: Run id, start time, requested cases, fingerprint, seed and flags.
        end: Cost of judge calls, duration, counters, stop reason and judged cases.
        registry: Source of ``metric_versions``.

    Returns:
        The manifest; ``judge_degraded`` is set when judge errors exceed 5 % of the judged cases.
    """
    counts, judged = end.counts, end.judged_cases
    degraded = judged > 0 and counts["judge_error"] / judged > JUDGE_ERROR_SHARE
    return RunManifest(
        schema_version="1",
        run_id=facts.run_id,
        created_at=facts.created_at,
        pruefstand_version=_package_version(),
        git_sha=None,
        git_ref=None,
        pr_number=None,
        target=None,
        target_fingerprint=facts.target_fingerprint,
        **_PLACEHOLDERS,
        splits=tuple(dict.fromkeys(c.split for c in facts.cases)),
        n_cases=len(facts.cases),
        judged_subset=facts.judged_subset,
        metric_versions={m.name: m.version for m in registry.all()},
        seed=facts.seed,
        cost=CostSummary(
            usd=end.cost.usd,
            prompt_tokens=end.cost.prompt_tokens,
            completion_tokens=end.cost.completion_tokens,
            gpu_seconds=0.0,
            llm_calls=end.cost.requests,
        ),
        duration_s=end.duration_s,
        counts={k: v for k, v in counts.items() if v},
        complete=end.stop_reason == "completed",
        stop_reason=end.stop_reason,
        stack="live",
        workload="pr",
        judge_mode="local" if facts.judges_given and judged else "skipped",
        judge_degraded=degraded,
        judged_cases=judged,
    )
