"""Which judge calls a run makes: the ambiguity rule (W3.5) and the tier-1 case selection (W1.4)."""

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache
from importlib import resources

from pruefstand.core.enums import Category
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.llm.policy import contains_canary
from pruefstand.metrics.deterministic.normalise import security_normalise
from pruefstand.metrics.deterministic.refusal import is_refusal
from pruefstand.metrics.judged.base import JudgedBase

SHORT_ANSWER_WORDS = 40
_DIGIT = re.compile(r"\d")


@lru_cache(maxsize=1)
def _hedges() -> tuple[str, ...]:
    resource = resources.files("pruefstand.metrics").joinpath("data", "refusal_hedges.txt")
    lines = (line.strip() for line in resource.read_text(encoding="utf-8").splitlines())
    return tuple(security_normalise(line) for line in lines if line and not line.startswith("#"))


def is_ambiguous(resp: TargetResponse) -> bool:
    """Whether the phrase list cannot tell if ``resp`` refuses (round 9 AI9-19).

    Ambiguous means: no refusal phrase **and** (a hedge from ``refusal_hedges.txt``, **or** an
    answer of at most 40 words without a citation and without a number).

    Examples:
        >>> is_ambiguous(TargetResponse(answer="Das lässt sich nicht eindeutig sagen."))
        True
        >>> is_ambiguous(TargetResponse(answer="Die Frist beträgt 3 Monate."))
        False
        >>> refused = TargetResponse(answer="Dazu liegen keine Informationen vor.", refused=False)
        >>> is_ambiguous(refused)
        False
    """
    answer = resp.answer
    if is_refusal(answer):
        return False
    haystack = security_normalise(answer)
    if any(hedge in haystack for hedge in _hedges()):
        return True
    cited = bool(resp.citations) or "§" in answer
    return len(answer.split()) <= SHORT_ANSWER_WORDS and not cited and not _DIGIT.search(answer)


_PROBES = frozenset(
    {Category.LEAK_PROBE, Category.FILTER_BYPASS, Category.SYSTEM_PROMPT_EXTRACTION}
)


def planned_calls(case: TestCase, metrics: Iterable[JudgedBase]) -> int:
    """Upper bound of the judge calls of ``case``: one per metric that can apply to it."""
    return sum(1 for m in metrics if m.applicable(case))


def case_holds_canary(case: TestCase, canaries: CanaryRegistry | None) -> bool:
    """Whether ``case`` is a probe or its question / reference holds a registered canary.

    Such a case is never judged: its rendered judge inputs would carry canary text (D9-06).
    """
    if case.category in _PROBES:
        return True
    texts = [case.question, case.reference_answer or ""]
    return canaries is not None and contains_canary(texts, canaries)


def select_judged_cases(
    cases: Sequence[TestCase],
    metrics: Sequence[JudgedBase],
    *,
    dataset_version: str,
    max_calls: int,
    canaries: CanaryRegistry | None,
) -> frozenset[str]:
    """Pick the cases a capped (tier-1) run judges: as many as fit in ``max_calls`` judge calls.

    The order is a hash of the dataset version and the case id, so the baseline run and the PR
    run of one dataset version judge the same ids (``eval_fingerprint`` plays no part). A case
    with a registered canary in its inputs is dropped before counting. One call is kept free for
    the repair of the last call (the runner reserves two per call), so ``max_calls`` calls
    plan to ``max_calls - 1``.

    Args:
        cases: The cases of the run.
        metrics: The judged metrics.
        dataset_version: Seeds the order.
        max_calls: The run's ``budget.max_requests_per_run``.
        canaries: Registered canaries, or None.

    Returns:
        The ids of the selected cases (cases that no judged metric applies to are not selected).
    """
    room = max_calls - 1
    ordered = sorted(cases, key=lambda c: stable_hash(dataset_version, str(c.id)))
    chosen: set[str] = set()
    used = 0
    for case in ordered:
        calls = planned_calls(case, metrics)
        if calls == 0 or case_holds_canary(case, canaries) or used + calls > room:
            continue
        chosen.add(str(case.id))
        used += calls
    return frozenset(chosen)
