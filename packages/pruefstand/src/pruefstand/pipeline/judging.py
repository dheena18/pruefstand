"""The judge side of a run: shared budget and call log, canaries, case selection, family check."""

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pruefstand.core.config import ModelRef, PruefstandConfig
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.core.protocols import JudgePoolLike, KVCache
from pruefstand.judges.exact_tokens import load_counter
from pruefstand.judges.family_guard import check_judge_families
from pruefstand.llm.budget import Budget
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.metrics.judged.base import JudgedBase
from pruefstand.metrics.judged.routing import select_judged_cases
from pruefstand.pipeline.abort import write_aborted_run
from pruefstand.pipeline.plan import Plan
from pruefstand.runner.judging import JudgeScope
from pruefstand.store.canary_source import load_canary_registry

_log = get_logger(__name__)
PoolBuilder = Callable[..., JudgePoolLike | None]


@dataclass(frozen=True)
class JudgeSetup:
    """What the pool, the runner and the manifest share: one budget, one call log, the canaries.

    Attributes:
        budget: The run budget (the runner reserves from it, every judge client charges it).
        recorder: One row per judge call; ``fallback_used(recorder.rows)`` is ``judge_fallback``.
        pool: The judge pool, or None (mode ``skipped``, or the canary registry is unavailable
            for an external judge).
        scope: Selected case ids and canaries for the runner.
    """

    budget: Budget
    recorder: CallRecorder
    pool: JudgePoolLike | None
    scope: JudgeScope


def _external(refs: Iterable[ModelRef | None]) -> bool:
    return any(ref is not None and provider_of(ref.id) not in LOCAL_PROVIDERS for ref in refs)


def judge_refs(cfg: PruefstandConfig) -> list[ModelRef]:
    """Every judge the run can use: PR, nightly, per-metric ones."""
    return [cfg.judge.pr, cfg.judge.nightly, *cfg.judge.per_metric.values()]


def load_canaries(
    cfg: PruefstandConfig, env: Mapping[str, str] | None = None
) -> CanaryRegistry | None:
    """Load the canary registry; None when it is unreadable and an external judge is configured.

    Fails closed whenever ANY external judge (a judge or ``llm.fallback_judge``) is configured: an
    empty registry would let canary or private text reach that provider (a fallback answers after
    a primary 429). Only a purely local setup (D328) may run without a registry.
    """
    try:
        return load_canary_registry(root=Path.cwd(), env=os.environ if env is None else env)
    except StoreError:
        if _external([*judge_refs(cfg), cfg.llm.fallback_judge]):
            _log.warning("judge_canaries_unavailable", detail="external judge skipped")
            return None
        return CanaryRegistry(canaries=())


def prepare_judging(plan: Plan, build: PoolBuilder, cache: KVCache | None) -> JudgeSetup:
    """Build the budget, call log, pool and case scope of a run.

    Args:
        plan: The plan (config, tier, requested judge mode, cases, registry).
        build: ``pipeline.judge_mode.build_judge_pool`` (passed in so tests can replace it).
        cache: The ``llm`` namespace cache of the job, or None.

    Returns:
        The setup. With a request cap (tier 1) the scope selects the cases to judge by dataset
        version, so baseline and PR judge the same ids.

    Raises:
        ConfigError: No nonce key, or a judge client cannot be built.
    """
    cfg = plan.cfg
    budget = Budget(
        max_usd=cfg.budget.max_usd_per_run,
        max_tokens=cfg.budget.max_tokens_per_run,
        max_requests=cfg.budget.max_requests_per_run,
    )
    recorder = CallRecorder()
    canaries = None if plan.mode == "skipped" else load_canaries(cfg)
    guarded = plan.mode != "skipped" and canaries is not None
    pool = None
    if guarded:
        pool = build(
            cfg, plan.mode, tier=plan.tier, budget=budget, recorder=recorder,
            canaries=canaries, cache=cache,
        )  # fmt: skip
    # the canary scope (canary_in_input, selection) is for external judges; a local one may see them
    scoped = canaries if _external(judge_refs(cfg)) else None
    return JudgeSetup(budget, recorder, pool, _scope(plan, scoped, pooled=pool is not None))


def _scope(plan: Plan, canaries: CanaryRegistry | None, *, pooled: bool) -> JudgeScope:
    cap = plan.cfg.budget.max_requests_per_run
    judged = [m for m in plan.registry.all() if isinstance(m, JudgedBase)]
    if not pooled or cap is None or not judged:
        return JudgeScope(None, canaries)
    chosen = select_judged_cases(
        plan.cases, judged, dataset_version=plan.data.version, max_calls=cap, canaries=canaries
    )
    return JudgeScope(chosen, canaries)


def checked_pool(
    plan: Plan, pool: JudgePoolLike | None, info: TargetInfo | None, out: Path
) -> tuple[JudgePoolLike | None, bool]:
    """Apply the run-time family rule after ``/v1/info`` and before any judge call.

    Every configured judge and ``llm.fallback_judge`` must come from another family than the
    target's generator. An opaque target (no ``/v1/info``) cannot be checked: the run goes on
    with a warning, like the corpus check.

    Returns:
        The pool and whether the family check was skipped (opaque target; the run records
        ``counts["judge_family_unchecked"]``).

    Raises:
        ConfigError: A judge shares the generator's family; an aborted run (``complete=False``,
            ``stop_reason="aborted"``, no judge call) is written first and named in the message.
    """
    if pool is None:
        return None, False
    if info is None:
        _log.warning("judge_family_unchecked", detail="opaque target; generator family unknown")
        return pool, True
    try:
        check_judge_families(plan.cfg.judge, [info], plan.cfg.llm.fallback_judge)
    except ConfigError as exc:
        directory = write_aborted_run(plan, info, out, "judge_family")
        msg = f"{exc}; aborted run {directory}"
        raise ConfigError(msg) from exc
    return pool, False


def exact_count_missing(pool: JudgePoolLike | None, cfg: PruefstandConfig) -> bool:
    """Whether a judge of the run lacks its exact tokenizer (cut sign (3) is skipped)."""
    if pool is None:
        return False
    return any(
        provider_of(ref.id) == "ollama" and load_counter(ref.id) is None for ref in judge_refs(cfg)
    )


def count_up(results: RunResults, key: str) -> RunResults:
    """Return ``results`` with ``manifest.counts[key]`` set to 1 (recorded, not only logged)."""
    manifest = results.manifest.model_copy(update={"counts": {**results.manifest.counts, key: 1}})
    return results.model_copy(update={"manifest": manifest})
