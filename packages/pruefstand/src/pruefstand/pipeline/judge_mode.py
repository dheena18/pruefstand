"""Stack and judge mode of a run (T1.10 S4, round-8 W1.4 / W3.9).

``judge_mode`` is ``local`` (tier 2) or ``skipped``; ``github`` (the tier-1 GitHub Models judge)
is retired (2026-07-30, D1202): it is never selected and a request for it is refused. It stays in
``JudgeMode`` only so older ``run.json`` files still read. There is no CPU judge in any tier.
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from pruefstand.core.config import ModelRef, PruefstandConfig
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.run import ScoredCase
from pruefstand.core.protocols import JudgePoolLike, KVCache
from pruefstand.judges.factory import build_pool
from pruefstand.llm.budget import Budget
from pruefstand.llm.cache_epochs import read_drift
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_client
from pruefstand.llm.recorder import CallRecorder
from pruefstand.pipeline.select import Tier

Stack = Literal["live", "a40"]
JudgeMode = Literal["github", "local", "skipped"]
_STACKS: tuple[Stack, ...] = ("live", "a40")
_MODES: tuple[JudgeMode, ...] = ("local", "skipped")
RETIRED = "GitHub Models is retired (2026-07-30, D1202)"
_SHOWABLE = re.compile(r"[a-z0-9_-]{1,12}")


def _shown(value: str) -> str:
    """Echo a bad value only when it looks like a word, never a long or odd string (a secret)."""
    return repr(value) if _SHOWABLE.fullmatch(value) else "<unrecognised>"


def resolve_stack(env: Mapping[str, str]) -> Stack:
    """Return the stack named by ``PRUEFSTAND_STACK`` (default ``live``).

    Args:
        env: The environment.

    Returns:
        ``"live"`` or ``"a40"``.

    Raises:
        ConfigError: The variable holds anything else.

    Examples:
        >>> resolve_stack({})
        'live'
        >>> resolve_stack({"PRUEFSTAND_STACK": "a40"})
        'a40'
    """
    value = env.get("PRUEFSTAND_STACK") or "live"
    for stack in _STACKS:
        if value == stack:
            return stack
    msg = f"PRUEFSTAND_STACK={_shown(value)}: must be one of {', '.join(_STACKS)}"
    raise ConfigError(msg)


def requested_judge_mode(
    *, stack: Stack, env: Mapping[str, str], has_models_token: bool
) -> JudgeMode:
    """Decide the judge mode before the run.

    ``PRUEFSTAND_JUDGE_MODE`` names the mode explicitly. Without it the mode follows the stack:
    ``live`` is ``skipped`` (no tier-1 judge since D1202, whether or not an old GitHub Models token
    is set), ``a40`` is ``local``.

    Args:
        stack: ``live`` or ``a40``.
        env: The environment.
        has_models_token: Whether ``PRUEFSTAND_GH_MODELS_TOKEN`` is set; ignored since D1202 (kept
            so the signature in ``interfaces.md`` is unchanged).

    Returns:
        The requested mode.

    Raises:
        ConfigError: ``PRUEFSTAND_JUDGE_MODE`` is ``github`` (retired) or not ``local`` /
            ``skipped`` (``cpu`` never existed as a tier).

    Examples:
        >>> requested_judge_mode(stack="a40", env={}, has_models_token=False)
        'local'
        >>> requested_judge_mode(stack="live", env={}, has_models_token=True)
        'skipped'
    """
    del has_models_token  # D1202: a token never selects the retired GitHub Models judge
    value = env.get("PRUEFSTAND_JUDGE_MODE")
    if value == "github":
        msg = f"PRUEFSTAND_JUDGE_MODE=github: {RETIRED}; use skipped (tier 1) or local (tier 2)"
        raise ConfigError(msg)
    if value:
        for mode in _MODES:
            if value == mode:
                return mode
        msg = f"PRUEFSTAND_JUDGE_MODE={_shown(value)}: must be one of {', '.join(_MODES)}"
        raise ConfigError(msg)
    return "local" if stack == "a40" else "skipped"


def final_judge_mode(
    requested: JudgeMode, *, judged_cases: int, quota_skipped: int = 0
) -> JudgeMode:
    """Downgrade to ``skipped`` when no judged value was produced or the quota ran out.

    Args:
        requested: The mode from ``requested_judge_mode``.
        judged_cases: Cases with a judged value (runner result).
        quota_skipped: Judged values skipped with reason ``judge_quota`` (W1.4: the remaining
            judged metrics are skipped, never handed to another judge).

    Returns:
        The mode to record in ``run.json``.

    Examples:
        >>> final_judge_mode("github", judged_cases=0)
        'skipped'
        >>> final_judge_mode("github", judged_cases=4, quota_skipped=1)
        'skipped'
    """
    return requested if judged_cases > 0 and quota_skipped == 0 else "skipped"


def quota_skipped(values: Iterable[ScoredCase]) -> int:
    """Count the metric values the runner skipped because the judge quota was exhausted."""
    return sum(
        1
        for scored in values
        for value in scored.values
        if value.details.get("reason") == "judge_quota"
    )


def fallback_used(rows: Iterable[Mapping[str, object]]) -> bool:
    """Return True when any recorded judge call was answered by the fallback judge (Y4.4).

    Args:
        rows: ``CallRecorder.rows`` of the run's judge calls.
    """
    return any(row.get("fallback") is True for row in rows)


def judge_ids(cfg: PruefstandConfig, tier: str) -> frozenset[str]:
    """Return the judge model ids a run of ``tier`` can use (default judge and per-metric ones)."""
    default = cfg.judge.nightly if tier == "nightly" else cfg.judge.pr
    return frozenset({default.id, *(ref.id for ref in cfg.judge.per_metric.values())})


def judge_drift_flag(cache_dir: Path, models: Iterable[str]) -> bool:
    """Return True when ``judge_drift.json`` flags one of ``models`` (S13).

    The flag marks judged metrics informational (``judge_drift``); it never touches
    ``eval_fingerprint``.

    Raises:
        ConfigError: The drift file exists but is invalid.
    """
    flag = read_drift(cache_dir)
    return flag is not None and flag.model in set(models)


def build_judge_pool(
    cfg: PruefstandConfig,
    mode: JudgeMode,
    *,
    tier: Tier,
    budget: Budget,
    recorder: CallRecorder,
    canaries: CanaryRegistry,
    cache: KVCache | None,
) -> JudgePoolLike | None:
    """Build the judge pool of a run: every judge client shares the run's budget and call log.

    Args:
        cfg: The run configuration (``judge``, ``llm`` policy and fallback judge).
        mode: The requested mode; ``skipped`` builds nothing.
        tier: ``pr``, ``nightly`` or ``bench`` (``nightly`` uses ``judge.nightly``).
        budget: The run budget, the same object the runner reserves from.
        recorder: Receives one row per judge call (``fallback_used`` reads it).
        canaries: Registry for the external-provider data guard (fail closed).
        cache: The ``llm`` namespace cache, or None.

    Returns:
        The pool, or None for ``skipped``.

    Raises:
        ConfigError: No ``PRUEFSTAND_NONCE_KEY``, or a judge backend cannot be built.
    """
    if mode == "skipped":
        return None

    def make_client(ref: ModelRef) -> LLMClient:
        return build_client(cfg, cache, budget, recorder, model=ref, canaries=canaries)

    return build_pool(cfg, tier=tier, make_client=make_client)
