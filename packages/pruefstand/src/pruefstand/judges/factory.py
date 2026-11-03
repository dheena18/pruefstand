"""Build the ``JudgePool`` of a run from the configuration."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pruefstand.core.config import ModelRef, PruefstandConfig
from pruefstand.judges.judge import Judge, JudgePool
from pruefstand.llm.client import LLMClient
from pruefstand.llm.prompts import PromptRegistry

DEFAULT_KEY = "default"
PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"


def build_pool(
    cfg: PruefstandConfig,
    *,
    tier: Literal["pr", "nightly", "bench"],
    make_client: Callable[[ModelRef], LLMClient],
    registry: PromptRegistry | None = None,
    nonce_key: bytes | None = None,
) -> JudgePool:
    """Build the pool: the tier's default judge plus one judge per ``judge.per_metric`` entry.

    A model that serves several metrics gets one client and one ``Judge``.

    Args:
        cfg: The run configuration.
        tier: ``nightly`` uses ``judge.nightly``; ``pr`` and ``bench`` use ``judge.pr``.
        make_client: Builds the ``LLMClient`` of a judge model. The runner passes one that shares
            its budget, call recorder and canary registry (T5.2b).
        registry: Prompt registry; default the shipped ``judges/prompts``.
        nonce_key: HMAC key of the block nonces; default ``PRUEFSTAND_NONCE_KEY``.

    Returns:
        The pool; every metric without its own judge uses the default.

    Raises:
        ConfigError: No nonce key, or a client cannot be built.
    """
    prompts = registry or PromptRegistry([PROMPT_ROOT])
    default = cfg.judge.nightly if tier == "nightly" else cfg.judge.pr
    made: dict[str, Judge] = {}

    def judge_for(ref: ModelRef) -> Judge:
        if ref.id not in made:
            made[ref.id] = Judge(make_client(ref), ref.id, prompts, nonce_key=nonce_key)
        return made[ref.id]

    judges = {DEFAULT_KEY: judge_for(default)}
    judges.update({metric: judge_for(ref) for metric, ref in cfg.judge.per_metric.items()})
    return JudgePool(judges, DEFAULT_KEY)
