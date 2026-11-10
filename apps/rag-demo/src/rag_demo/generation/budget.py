"""Prompt budget of the Ollama generator, counted with the generator's own tokenizer (AI13-05).

Ollama silently truncates a prompt longer than ``num_ctx``, so the app counts it first. The count
wraps every message the way the Qwen chat template does (ChatML role markers and the empty think
block of ``think: false``); the ``bge-m3`` tokenizer is never used here (it undercounts
German).
Calibrated on the real A40 generator (D960): the count equals Ollama's ``prompt_eval_count``
exactly unless Ollama cut the prompt, which it reports as about ``num_ctx / 2``; only the local
count sees that.
"""

import logging

from rag_demo.generation.prompting import build_prompt
from rag_demo.index.tokens import TokenCounter
from rag_demo.models import Hit, RagConfig

_log = logging.getLogger(__name__)
TOLERANCE = 0.02
_GENERATION_PREFIX = "<|im_start|>assistant\n"
_EMPTY_THINK = "<think>\n\n</think>\n\n"


def prompt_budget(cfg: RagConfig) -> int | None:
    """``num_ctx`` minus ``num_predict`` for an Ollama generator, else ``None`` (no budget)."""
    if cfg.generator.engine != "ollama" or cfg.generation is None:
        return None
    num_ctx = cfg.generator.options.get("num_ctx")
    return int(num_ctx) - cfg.generation.max_tokens if num_ctx is not None else None


def count_prompt_tokens(messages: list[dict[str, str]], count: TokenCounter, cfg: RagConfig) -> int:
    """Tokens of the chat prompt as the model sees it (ChatML wrapper of the Qwen template)."""
    text = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    text += _GENERATION_PREFIX
    if not cfg.generator.enable_thinking:
        text += _EMPTY_THINK
    return count(text)


def fit_hits(
    question: str,
    hits: list[Hit],
    cfg: RagConfig,
    count: TokenCounter | None,
) -> list[Hit]:
    """Drop the lowest-ranked hits until the prompt fits ``num_ctx − num_predict``.

    Without a budget or a counter all hits are kept. The dropped hits are logged by id (never
    their text); the API returns them with ``used_in_prompt: false``.
    """
    budget = prompt_budget(cfg)
    if budget is None or count is None:
        return hits
    kept = list(hits)
    while len(kept) > 1 and count_prompt_tokens(build_prompt(question, kept, cfg), count, cfg) > (
        budget
    ):
        kept.pop()
    if len(kept) < len(hits):
        _log.warning(
            "prompt over budget %d: dropped %d of %d chunks %s",
            budget,
            len(hits) - len(kept),
            len(hits),
            [h.chunk_id for h in hits[len(kept) :]],
        )
    return kept


def is_overflow(reported: int, local: int | None, budget: int | None) -> bool:
    """True when Ollama's ``prompt_eval_count`` hints at truncation (D307).

    That is ``reported >= budget``, or a local count that differs by more than 2 %.

    Examples:
        >>> is_overflow(1030, 1000, 7936)
        True
        >>> is_overflow(1010, 1000, 7936)
        False
        >>> is_overflow(7936, None, 7936)
        True
    """
    if budget is not None and reported >= budget:
        return True
    return local is not None and local > 0 and abs(reported - local) / local > TOLERANCE
