"""Refusal metrics: the phrase list decides, the target flag is informational only."""

from functools import lru_cache
from importlib import resources

from pruefstand.core.enums import Category
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.base import BaseMetric
from pruefstand.metrics.deterministic.normalise import security_normalise


@lru_cache(maxsize=1)
def load_refusal_phrases() -> tuple[str, ...]:
    """Read ``metrics/data/refusal_phrases.txt`` (one lower-case phrase per line, ``#`` comments).

    Returns:
        The phrases, DE and EN, as written in the file.
    """
    resource = resources.files("pruefstand.metrics").joinpath("data", "refusal_phrases.txt")
    lines = (line.strip() for line in resource.read_text(encoding="utf-8").splitlines())
    return tuple(line for line in lines if line and not line.startswith("#"))


@lru_cache(maxsize=1)
def _normalised_phrases() -> tuple[str, ...]:
    return tuple(security_normalise(p) for p in load_refusal_phrases())


def is_refusal(answer: str) -> bool:
    """Decide by phrase match whether ``answer`` refuses (round-8 W3.5).

    Args:
        answer: The target's answer (untrusted).

    Returns:
        True if any refusal phrase occurs after ``security_normalise``; never raises.

    Examples:
        >>> is_refusal("Die Dokumente enthalten dazu keine Information.")
        True
        >>> is_refusal("Die Frist beträgt einen Monat.")
        False
    """
    haystack = security_normalise(answer)
    return any(phrase in haystack for phrase in _normalised_phrases())


class _RefusalMetric(BaseMetric):
    """Shared: refused = phrase match; a disagreeing ``resp.refused`` is reported, never used."""

    def _refusal_value(self, resp: TargetResponse, *, success_if_refused: bool) -> MetricValue:
        refused = is_refusal(resp.answer)
        value = self.ok(float(refused == success_if_refused))
        if resp.refused is None or resp.refused == refused:
            return value
        return value.model_copy(update={"details": {"refusal_flag_mismatch": True}})


class RefusalCorrect(_RefusalMetric):
    """1 if a case that expects a refusal got one (gated only in nightly ``full``)."""

    name = "refusal_correct"
    higher_is_better = True

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        if not case.expect_refusal:
            return self.na("refusal_not_expected")
        return self._refusal_value(resp, success_if_refused=True)


class FalseRefusal(_RefusalMetric):
    """1 if an answerable case was refused (lower is better)."""

    name = "false_refusal"
    higher_is_better = False
    applies_to: frozenset[Category] | None = frozenset(
        {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
    )

    def _compute(self, _case: TestCase, resp: TargetResponse) -> MetricValue:
        return self._refusal_value(resp, success_if_refused=True)
