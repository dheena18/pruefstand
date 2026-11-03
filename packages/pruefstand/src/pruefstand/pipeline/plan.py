"""What a run decided before its first request, and how the manifest and the run are finished."""

import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.fingerprint import target_fingerprint
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline.cache import trusted_target_id
from pruefstand.pipeline.datasets import Dataset
from pruefstand.pipeline.fingerprints import JudgeFacts, build_eval_fingerprint
from pruefstand.pipeline.judge_mode import JudgeMode, Stack
from pruefstand.pipeline.provenance import read_provenance
from pruefstand.pipeline.select import Stratum, Tier
from pruefstand.store.artifacts import ArtifactStore, new_run_id


@dataclass(frozen=True)
class Plan:
    """Everything decided before the first request."""

    cfg: PruefstandConfig
    tier: Tier
    stack: Stack
    mode: JudgeMode
    data: Dataset
    cases: tuple[TestCase, ...]
    registry: MetricRegistry
    judges: JudgeFacts
    block: int | None
    judged_subset: bool
    stratum: Stratum

    def eval_fingerprint(self) -> str:
        """The ``eval_fingerprint`` of this plan (``core.fingerprint`` does the hashing)."""
        return build_eval_fingerprint(
            self.judges,
            name=self.data.name,
            version=self.data.version,
            corpus_version=self.data.corpus_version,
            splits=self.cfg.splits,
            metric_versions={m.name: m.version for m in self.registry.all()},
            block=self.block,
            judged_subset=self.judged_subset,
            stratum=self.stratum,
        )


def complete_manifest(
    manifest: RunManifest,
    plan: Plan,
    info: TargetInfo | None,
    judge_mode: JudgeMode,
    *,
    judge_fallback: bool = False,
) -> RunManifest:
    """Fill what the runner does not know: dataset, config, judges, provenance, fingerprints."""
    facts = read_provenance(os.environ)
    return manifest.model_copy(
        update={
            "git_sha": facts.git_sha,
            "git_ref": facts.git_ref,
            "pr_number": facts.pr_number,
            "target": info,
            "eval_fingerprint": plan.eval_fingerprint(),
            "dataset_name": plan.data.name,
            "dataset_version": plan.data.version,
            "splits": plan.cfg.splits,
            "block": plan.block,
            "stratum": plan.stratum,
            "config_hash": stable_hash(plan.cfg),
            "judge_models": plan.judges.models,
            "judge_prompt_versions": plan.judges.prompt_versions,
            "judge_serving": plan.judges.serving,
            "judge_epoch": plan.judges.epoch,
            "stack": plan.stack,
            "workload": plan.tier,
            "judge_mode": judge_mode,
            "judge_fallback": judge_fallback,
        }
    )


def fingerprint_of_target(plan: Plan, info: TargetInfo | None) -> str:
    """Self-reported fingerprint; a trusted id from the executor is added to it, never replaced."""
    fingerprint = target_fingerprint(info, url=plan.cfg.target.url, run_id=new_run_id())
    trusted = trusted_target_id(os.environ)
    return fingerprint if trusted is None else stable_hash(trusted, fingerprint)


def store_run(out: Path, results: RunResults, llm_calls: pl.DataFrame | None = None) -> Path:
    """Write the run to ``out / <run_id>``; ``llm_calls`` is stored as ``llm_calls.parquet``."""
    root = out / results.manifest.run_id
    return ArtifactStore(out).write_run(
        RunArtifacts(results=results, root=root), llm_calls=llm_calls
    )
