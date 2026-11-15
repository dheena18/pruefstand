"""``run_eval``: config and cases in, a stored run directory out (T1.10 S2).

Order of work: validate flags, load config-selected cases, build the adapter, check the corpus
version and the judge families (before any query), filter cases, fingerprints, ``Runner.run``,
complete the manifest, write the run. Fingerprints come from ``pruefstand.core.fingerprint`` only.
"""

import os
from pathlib import Path

from pruefstand.adapters.factory import build_adapter
from pruefstand.core.config import PruefstandConfig
from pruefstand.core.logging import get_logger
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.core.protocols import JudgePoolLike, KVCache, TargetAdapter
from pruefstand.core.settings import PruefstandSettings
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline.abort import abort_on_corpus_mismatch
from pruefstand.pipeline.cache import (
    cache_mode,
    identity_is_opaque,
    reads_base,
    target_cache,
    trusted_target_id,
)
from pruefstand.pipeline.datasets import load_dataset
from pruefstand.pipeline.fingerprints import judge_facts
from pruefstand.pipeline.judge_mode import (
    build_judge_pool,
    fallback_used,
    final_judge_mode,
    judge_drift_flag,
    judge_ids,
    quota_skipped,
    requested_judge_mode,
    resolve_stack,
)
from pruefstand.pipeline.judging import (
    JudgeSetup,
    checked_pool,
    count_up,
    exact_count_missing,
    prepare_judging,
)
from pruefstand.pipeline.plan import Plan, complete_manifest, fingerprint_of_target, store_run
from pruefstand.pipeline.select import Stratum, Tier, select_cases, validate_selection
from pruefstand.runner.runner import Runner

_log = get_logger(__name__)


def build_registry() -> MetricRegistry:
    """The metric registry of a run: the deterministic metrics and the four judged ones (T5.2b)."""
    return MetricRegistry.full()


def _plan(
    cfg: PruefstandConfig, tier: Tier, *, block: int | None, judged_subset: bool, stratum: Stratum
) -> Plan:
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
    return Plan(
        cfg, tier, stack, mode, data, tuple(cases), build_registry(),
        judge_facts(cfg, stack=stack, tier=tier), block, judged_subset, stratum,
    )  # fmt: skip


def _runner(
    plan: Plan,
    adapter: TargetAdapter,
    setup: JudgeSetup,
    judges: JudgePoolLike | None,
    cache: KVCache | None,
) -> Runner:
    return Runner(
        adapter,
        plan.registry,
        judges,
        cache,
        setup.budget,
        plan.cfg.runner,
        judge_scope=setup.scope,
    )


async def _execute(
    plan: Plan, setup: JudgeSetup, out: Path
) -> tuple[RunResults, TargetInfo | None]:
    """Ask the target for its info, check corpus and judge families, then run the cases.

    The target cache is opened only now, because it depends on the identity the target reports:
    an opaque identity gets no cache, and without ``PRUEFSTAND_TRUSTED_TARGET_ID`` a PR job never
    reads main's cache (D446).
    """
    adapter = build_adapter(plan.cfg.target)
    try:
        info = await adapter.info()
        abort_on_corpus_mismatch(plan, info, out)
        judges, unchecked = checked_pool(plan, setup.pool, info, out)
        usable = not identity_is_opaque(info)
        if not usable:
            _log.warning("target_cache_off", note="the target reports no usable identity")
        trusted = trusted_target_id(os.environ)
        with target_cache(
            os.environ, enabled=usable, use_base=reads_base(usable=usable, trusted=trusted)
        ) as cache:
            results = await _runner(plan, adapter, setup, judges, cache).run(
                plan.cases,
                target_fingerprint=fingerprint_of_target(plan, info),
                seed=plan.cfg.seed,
                judged_subset=plan.judged_subset,
            )
        results = _mark_base_hits(results, base_read=reads_base(usable=usable, trusted=trusted))
        if unchecked:
            results = count_up(results, "judge_family_unchecked")
        if exact_count_missing(judges, plan.cfg):
            results = count_up(results, "judge_exact_count_unavailable")
    finally:
        await adapter.aclose()
    return results, info


def _mark_base_hits(results: RunResults, *, base_read: bool) -> RunResults:
    """Record ``cached_from_base``: answers a PR candidate got from main's cache (D446)."""
    cached = results.manifest.counts.get("cached", 0)
    if not base_read or cache_mode(os.environ) != "overlay" or cached == 0:
        return results
    counts = {**results.manifest.counts, "cached_from_base": cached}
    return results.model_copy(
        update={"manifest": results.manifest.model_copy(update={"counts": counts})}
    )


def _finish(
    plan: Plan, results: RunResults, info: TargetInfo | None, setup: JudgeSetup, out: Path
) -> RunResults:
    """Complete the manifest (judge mode, fallback, drift), write the run and return it."""
    mode = final_judge_mode(
        plan.mode,
        judged_cases=results.manifest.judged_cases,
        quota_skipped=quota_skipped(results.values),
    )
    manifest = complete_manifest(
        results.manifest, plan, info, mode, judge_fallback=fallback_used(setup.recorder.rows)
    )
    drift = judge_drift_flag(PruefstandSettings().cache_dir, judge_ids(plan.cfg, plan.tier))
    manifest = manifest.model_copy(update={"judge_drift": manifest.judge_drift or drift})
    done = results.model_copy(update={"manifest": manifest})
    store_run(out, done, setup.recorder.to_frame() if setup.recorder.rows else None)
    _log.info(
        "run_written", run_id=manifest.run_id, complete=manifest.complete, cases=len(plan.cases)
    )
    return done


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
    ``PRUEFSTAND_JUDGE_MODE``; the target cache from ``PRUEFSTAND_CACHE_MODE`` (``overlay`` by
    default, ``shared`` for main and nightly) and ``PRUEFSTAND_CACHE_DIR``; git facts from
    ``GITHUB_SHA`` / ``GITHUB_REF`` / ``GITHUB_EVENT_PATH`` or ``git``. An opaque target (no
    ``/v1/info``) continues with a warning. Judges share the run budget and call log
    (``llm_calls.parquet``); a call answered by ``llm.fallback_judge`` sets ``judge_fallback``.
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
            ``PRUEFSTAND_JUDGE_MODE``, no ``PRUEFSTAND_NONCE_KEY``, or a judge of the generator's
            family (an aborted run is written first).
        DatasetError: The dataset is invalid.
        CorpusMismatch: The target serves another corpus version; an aborted run is written first.
        TargetError: ``/v1/info`` failed with an error other than 404.
        StoreError: The run could not be written.
    """
    plan = _plan(cfg, tier, block=block, judged_subset=judged_subset, stratum=stratum)
    with target_cache(os.environ, enabled=plan.mode != "skipped", namespace="llm") as llm_cache:
        setup = prepare_judging(plan, build_judge_pool, llm_cache)
        results, info = await _execute(plan, setup, out)
    return _finish(plan, results, info, setup, out)
