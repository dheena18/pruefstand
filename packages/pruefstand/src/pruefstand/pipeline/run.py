"""``run_eval``: config and cases in, a stored run directory out (T1.10 S2).

Order of work: validate flags, load config-selected cases, build the adapter, check the corpus
version (before any query), filter cases, fingerprints, ``Runner.run``, complete the manifest, write
the run. Fingerprints come from ``pruefstand.core.fingerprint`` only.
"""

import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pruefstand.adapters.factory import build_adapter
from pruefstand.core.config import PruefstandConfig
from pruefstand.core.errors import CorpusMismatch
from pruefstand.core.fingerprint import target_fingerprint
from pruefstand.core.hashing import stable_hash
from pruefstand.core.logging import get_logger
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike, TargetAdapter
from pruefstand.llm.budget import Budget, ChargeTally
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline.datasets import Dataset, load_dataset
from pruefstand.pipeline.fingerprints import JudgeFacts, build_eval_fingerprint, judge_facts
from pruefstand.pipeline.judge_mode import (
    JudgeMode,
    Stack,
    build_judge_pool,
    final_judge_mode,
    requested_judge_mode,
    resolve_stack,
)
from pruefstand.pipeline.provenance import read_provenance
from pruefstand.pipeline.select import Stratum, Tier, select_cases, validate_selection
from pruefstand.runner.manifest import RunEnd, RunFacts, build_manifest
from pruefstand.runner.runner import Runner
from pruefstand.store.artifacts import ArtifactStore, new_run_id

_log = get_logger(__name__)


def build_registry() -> MetricRegistry:
    """The metric registry of a run (deterministic metrics; judged ones arrive with T5.2b)."""
    return MetricRegistry.default()


@dataclass(frozen=True)
class _Plan:
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


def _plan(
    cfg: PruefstandConfig, tier: Tier, *, block: int | None, judged_subset: bool, stratum: Stratum
) -> _Plan:
    env = os.environ
    stack = resolve_stack(env)
    mode = requested_judge_mode(
        stack=stack, env=env, has_models_token=bool(env.get("PRUEFSTAND_GH_MODELS_TOKEN"))
    )
    validate_selection(
        cfg.splits, tier=tier, block=block, judged_subset=judged_subset, stratum=stratum
    )
    data = load_dataset(cfg.dataset, cfg.splits)
    cases = select_cases(data.cases, block=block, stratum=stratum)
    return _Plan(
        cfg, tier, stack, mode, data, tuple(cases), build_registry(),
        judge_facts(cfg, stack=stack, tier=tier), block, judged_subset, stratum,
    )  # fmt: skip


def _complete(
    manifest: RunManifest, plan: _Plan, info: TargetInfo | None, judge_mode: JudgeMode
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
        }
    )


def _target_fingerprint(plan: _Plan, info: TargetInfo | None) -> str:
    return target_fingerprint(info, url=plan.cfg.target.url, run_id=new_run_id())


def _store(out: Path, results: RunResults) -> Path:
    root = out / results.manifest.run_id
    return ArtifactStore(out).write_run(RunArtifacts(results=results, root=root))


def _abort_on_corpus_mismatch(plan: _Plan, info: TargetInfo | None, out: Path) -> None:
    """Stop before any query when the target serves a corpus the dataset was not built for."""
    if info is None:
        _log.warning("target_info_unavailable", detail="opaque target; corpus version unchecked")
        return
    if info.corpus_version == plan.data.corpus_version:
        return
    facts = RunFacts(
        run_id=new_run_id(),
        created_at=datetime.now(UTC),
        cases=(),
        target_fingerprint=_target_fingerprint(plan, info),
        seed=plan.cfg.seed,
        judged_subset=plan.judged_subset,
        judges_given=False,
    )
    end = RunEnd(ChargeTally(), 0.0, Counter({"corpus_mismatch": 1}), "aborted", 0)
    manifest = _complete(build_manifest(facts, end, plan.registry), plan, info, "skipped")
    directory = _store(out, RunResults(manifest=manifest, records=(), values=()))
    msg = (
        f"target serves corpus {info.corpus_version!r}, dataset {plan.data.name} "
        f"{plan.data.version} was built for {plan.data.corpus_version!r}; aborted run {directory}"
    )
    raise CorpusMismatch(msg)


def _runner(plan: _Plan, adapter: TargetAdapter, judges: JudgePoolLike | None) -> Runner:
    budget = plan.cfg.budget
    return Runner(
        adapter,
        plan.registry,
        judges,
        None,
        Budget(
            max_usd=budget.max_usd_per_run,
            max_tokens=budget.max_tokens_per_run,
            max_requests=budget.max_requests_per_run,
        ),
        plan.cfg.runner,
    )


async def _execute(
    plan: _Plan, judges: JudgePoolLike | None, out: Path
) -> tuple[RunResults, TargetInfo | None]:
    """Ask the target for its info, check the corpus, then run the selected cases."""
    adapter = build_adapter(plan.cfg.target)
    try:
        info = await adapter.info()
        _abort_on_corpus_mismatch(plan, info, out)
        results = await _runner(plan, adapter, judges).run(
            plan.cases,
            target_fingerprint=_target_fingerprint(plan, info),
            seed=plan.cfg.seed,
            judged_subset=plan.judged_subset,
        )
    finally:
        await adapter.aclose()
    return results, info


async def run_eval(
    cfg: PruefstandConfig,
    *,
    tier: Tier,
    out: Path,
    block: int | None = None,
    judged_subset: bool = False,
    stratum: Stratum = "all",
) -> RunResults:
    """Evaluate the target of ``cfg`` on the selected cases and write a run directory.

    The run directory is ``out / <run_id>``. ``block`` is the resolved nightly block (the CLI
    resolves ``auto``). Stack and judge mode come from ``PRUEFSTAND_STACK`` (default ``live``) and
    ``PRUEFSTAND_JUDGE_MODE``; git facts from ``GITHUB_SHA`` / ``GITHUB_REF`` /
    ``GITHUB_EVENT_PATH`` or ``git``. An opaque target (no ``/v1/info``) continues with a warning.
    The returned results carry the manifest as the runner and the pipeline built it (the stored
    ``run.json`` also holds ``artifact_sha256``).

    Args:
        cfg: The configuration.
        tier: ``pr``, ``nightly`` or ``bench`` (recorded as ``workload``).
        out: Directory that holds run directories.
        block: Nightly block 0..2 or None (needs exactly the ``full`` split).
        judged_subset: Judged metrics and generation of ``core`` answerable cases on the judged
            subset only (needs ``core``).
        stratum: ``all``, ``refusal`` or ``blocks`` selector inside ``full``.

    Returns:
        The results of the run (complete or stopped early, see ``manifest.stop_reason``).

    Raises:
        ConfigError: Inconsistent flags, an ``hf://`` dataset, an invalid ``PRUEFSTAND_STACK`` or
            ``PRUEFSTAND_JUDGE_MODE``.
        DatasetError: The dataset is invalid.
        CorpusMismatch: The target serves another corpus version; an aborted run is written first.
        TargetError: ``/v1/info`` failed with an error other than 404.
        StoreError: The run could not be written.
    """
    plan = _plan(cfg, tier, block=block, judged_subset=judged_subset, stratum=stratum)
    judges = None if plan.mode == "skipped" else build_judge_pool(cfg, plan.mode)
    results, info = await _execute(plan, judges, out)
    mode = final_judge_mode(plan.mode, judged_cases=results.manifest.judged_cases)
    manifest = _complete(results.manifest, plan, info, mode)
    done = results.model_copy(update={"manifest": manifest})
    _store(out, done)
    _log.info(
        "run_written", run_id=manifest.run_id, complete=manifest.complete, cases=len(plan.cases)
    )
    return done
