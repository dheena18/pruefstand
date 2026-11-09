"""Fit the faithfulness context into the judge's input cap (round 9 X3.9)."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.protocols import JudgeLike
from pruefstand.judges.escaping import format_chunks

_SENTENCE_END = re.compile(r"[.!?:;](?=\s)|\n")


@dataclass(frozen=True, kw_only=True)
class Fitted:
    """The context that fits, how many tokens the prompt had before and has after.

    Attributes:
        task: The task to send (None when even an empty context does not fit).
        truncated: Whether chunks were dropped or the last one was cut.
        tokens_before: Estimated prompt tokens with every chunk.
        tokens_after: Estimated prompt tokens of ``task`` (``tokens_before`` if untouched).
    """

    task: JudgeTask | None
    truncated: bool
    tokens_before: int
    tokens_after: int


def cut_at_sentence(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` characters, at the last sentence end when there is one.

    Examples:
        >>> cut_at_sentence("Satz eins. Satz zwei. Satz drei.", 25)
        'Satz eins. Satz zwei.'
        >>> cut_at_sentence("abcdefgh", 3)
        'abc'
    """
    head = text[: max(limit, 0)]
    if len(head) == len(text):
        return head
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    return head[: ends[-1]].rstrip() if ends else head


def fit_context(
    build: Callable[[str], JudgeTask], chunks: Sequence[str], judge: JudgeLike
) -> Fitted:
    """Return the task with as much of ``chunks`` as the judge's input cap allows.

    The lowest-ranked chunks are dropped first (the last in the sequence); when one chunk is
    left and still too long it is cut at a sentence boundary. Question, answer and reference are
    never cut: if the prompt is over the cap even without any chunk the result has ``task=None``.

    Args:
        build: Makes the task from the rendered ``kontext`` text.
        chunks: Context chunks in rank order.
        judge: The judge (``input_cap`` and ``prompt_tokens``).

    Returns:
        A ``Fitted``; ``truncated`` is False and ``task`` the full task when everything fits.
    """
    cap = judge.input_cap
    full = build(format_chunks(chunks))
    before = judge.prompt_tokens(full)
    if before <= cap:
        return Fitted(task=full, truncated=False, tokens_before=before, tokens_after=before)
    kept = list(chunks)
    while len(kept) > 1:
        kept.pop()
        task = build(format_chunks(kept))
        if judge.prompt_tokens(task) <= cap:
            return _fitted(task, before, judge)
    return _cut_last(build, kept, judge, before)


def _fitted(task: JudgeTask, before: int, judge: JudgeLike) -> Fitted:
    return Fitted(
        task=task, truncated=True, tokens_before=before, tokens_after=judge.prompt_tokens(task)
    )


def _cut_last(
    build: Callable[[str], JudgeTask], kept: list[str], judge: JudgeLike, before: int
) -> Fitted:
    only = kept[0] if kept else ""
    empty = build("")
    if judge.prompt_tokens(empty) > judge.input_cap:
        return Fitted(
            task=None, truncated=True, tokens_before=before, tokens_after=judge.prompt_tokens(empty)
        )
    low, high = 0, len(only)  # the longest prefix that fits, by bisection on the length
    while low < high:
        middle = (low + high + 1) // 2
        probe = build(format_chunks([cut_at_sentence(only, middle)]))
        if judge.prompt_tokens(probe) <= judge.input_cap:
            low = middle
        else:
            high = middle - 1
    task = build(format_chunks([cut_at_sentence(only, low)]) if low else "")
    return _fitted(task, before, judge)


def over_cap(judge: JudgeLike, task: JudgeTask) -> bool:
    """True when the rendered prompt of ``task`` is over the judge's input cap."""
    return judge.prompt_tokens(task) > judge.input_cap
