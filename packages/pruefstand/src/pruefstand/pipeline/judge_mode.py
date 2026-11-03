"""Stack and judge mode of a run (T1.10 S4, round-8 W1.4 / W3.9).

``judge_mode`` is ``github`` (tier 1, informational), ``local`` (tier 2) or ``skipped``. There is
no CPU judge in any tier.
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import ScoredCase
from pruefstand.core.protocols import JudgePoolLike
from pruefstand.llm.cache_epochs import read_drift

Stack = Literal["live", "a40"]
JudgeMode = Literal["github", "local", "skipped"]
_STACKS: tuple[Stack, ...] = ("live", "a40")
_MODES: tuple[JudgeMode, ...] = ("github", "local", "skipped")
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

    ``PRUEFSTAND_JUDGE_MODE`` names the mode explicitly (``skipped`` for fork PRs). Without it the
    mode follows the stack: ``live`` is ``github`` (``skipped`` when no GitHub Models token is
    present), ``a40`` is ``local``.

    Args:
        stack: ``live`` or ``a40``.
        env: The environment.
        has_models_token: Whether ``PRUEFSTAND_GH_MODELS_TOKEN`` is set.

    Returns:
        The requested mode.

    Raises:
        ConfigError: ``PRUEFSTAND_JUDGE_MODE`` is not ``github``, ``local`` or ``skipped``
            (``cpu`` never existed as a tier).

    Examples:
        >>> requested_judge_mode(stack="a40", env={}, has_models_token=False)
        'local'
    """
    value = env.get("PRUEFSTAND_JUDGE_MODE")
    if value:
        for mode in _MODES:
            if value == mode:
                return mode
        msg = f"PRUEFSTAND_JUDGE_MODE={_shown(value)}: must be one of {', '.join(_MODES)}"
        raise ConfigError(msg)
    if stack == "a40":
        return "local"
    return "github" if has_models_token else "skipped"


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


def build_judge_pool(cfg: PruefstandConfig, mode: JudgeMode) -> JudgePoolLike | None:  # noqa: ARG001
    """Return the judge pool for ``mode``, or None while no judge exists.

    Judges (``pruefstand.judges``) arrive with T5.2a / T5.2b; until then judged metrics are not
    registered either, so ``None`` is correct and the run records ``judge_mode="skipped"``.

    Args:
        cfg: The run configuration.
        mode: The requested mode.

    Returns:
        None for now.
    """
    return None
