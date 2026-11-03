"""``faithfulness``: is the answer supported by exactly the chunks the generator saw?"""

from pruefstand.core.enums import Category
from pruefstand.core.logging import get_logger
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import RetrievedChunk, TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike
from pruefstand.judges.output import make_task
from pruefstand.metrics.judged.base import JudgedBase
from pruefstand.metrics.judged.truncate import fit_context

_log = get_logger(__name__)
_NOT_APPLICABLE = frozenset(
    {
        Category.UNANSWERABLE,
        Category.INJECTION,
        Category.LEAK_PROBE,
        Category.FILTER_BYPASS,
        Category.SYSTEM_PROMPT_EXTRACTION,
    }
)


def context_chunks(chunks: tuple[RetrievedChunk, ...], top_k: int | None) -> list[str]:
    """Return the texts of the chunks the generator saw, in rank order (W3.4, X3.14).

    The chunks with ``used_in_prompt=True``; when the target leaves the field ``None`` on every
    chunk, the first ``top_k`` returned chunks (all of them when ``top_k`` is None).

    Examples:
        >>> from pruefstand.core.models.target import RetrievedChunk as C
        >>> rows = tuple(C(chunk_id=f"c{i}", doc_id="d", text=f"t{i}", score=1.0, rank=i,
        ...                used_in_prompt=i % 2 == 0) for i in range(4))
        >>> context_chunks(rows, None)
        ['t0', 't2']
    """
    ranked = sorted(chunks, key=lambda c: c.rank)
    if all(c.used_in_prompt is None for c in ranked):
        return [c.text for c in ranked[:top_k]]
    return [c.text for c in ranked if c.used_in_prompt is True]


class Faithfulness(JudgedBase):
    """Faithfulness of the answer to its context (raw 0 / 1 / 2, scored 0 / 0.5 / 1).

    Args:
        top_k: How many returned chunks count as the generator's context when the target does
            not report ``used_in_prompt``; None takes all of them.
    """

    name = "faithfulness"
    version = "2"  # v2: not_applicable without a used chunk, judge-side reasons (T5.2b review)
    requires = frozenset({"chunks"})
    applies_to: frozenset[Category] | None = frozenset(Category) - _NOT_APPLICABLE

    def __init__(self, top_k: int | None = None) -> None:
        self._top_k = top_k

    async def acompute(
        self, case: TestCase, resp: TargetResponse, judges: JudgePoolLike
    ) -> MetricValue:
        """Judge ``resp.answer`` against the chunks of the prompt.

        Returns:
            ``not_applicable`` without returned chunks or when the question and answer alone are
            over the judge's input cap; otherwise the score (``details["truncated"]`` when
            context chunks were dropped or cut).

        Raises:
            LLMError: The judge failed (the runner turns it into an error value).
            BudgetExceeded: The call passed a budget limit.
        """
        if not resp.chunks:
            return self.na("missing_chunks")
        texts = context_chunks(resp.chunks, self._top_k)
        if not texts:
            return self.na("no_context_used")  # no chunk reached the generator prompt
        judge = judges.for_metric(self.name)

        def build(kontext: str) -> JudgeTask:
            return make_task(self.name, frage=case.question, kontext=kontext, antwort=resp.answer)

        fitted = fit_context(build, texts, judge)
        if fitted.task is None:
            return self.na("judge_input_too_long")
        verdict = await judge.score(fitted.task)
        if not fitted.truncated:
            return self.ok(verdict)
        _log.warning(
            "judge_input_truncated",
            case_id=str(case.id),
            metric=self.name,
            tokens_before=fitted.tokens_before,
            tokens_after=fitted.tokens_after,
            cap=judge.input_cap,
        )
        return self.ok(
            verdict,
            truncated=True,
            tokens_before=fitted.tokens_before,
            tokens_after=fitted.tokens_after,
        )
