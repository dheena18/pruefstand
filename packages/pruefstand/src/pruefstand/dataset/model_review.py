"""Model review of generated cases by a model of another family (T4.7a, SPEC §3.5 step 4).

``review_with_model`` asks the reviewer (German prompt ``review_item_de_v1``, JSON verdict
``ok | fix | reject``) about each case and then applies the deterministic overrides of
``dataset.review_checks``. Rules (round 9 X3.8, ADR-0019, D330):

* the reviewer's family differs from the generator's and from the datagen model's
  (``check_reviewer``); it is a local model, so private-tenant text never leaves our machines
  (``check_reviewer_for_case``, and the call is marked private so the ``LLMPolicy`` blocks any
  external provider too);
* the reviewer is reject-only: it never writes or rewrites a reference answer.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pruefstand.core.config import ModelRef
from pruefstand.core.enums import Category
from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import ModelVerdict, ReviewItem
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.generate_units import PROMPT_ROOT
from pruefstand.dataset.review import ATTACK_CATEGORIES
from pruefstand.dataset.review_checks import (
    CHUNK_MISSING,
    citation_matches,
    deterministic_item,
    deterministic_problems,
    finalise,
    lost_facts,
    source_chunks_of,
)
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.perturb.rewriter import PUBLIC_TENANT, private_text, request_prompt_id

__all__ = [
    "REVIEW_PROMPT",
    "ReviewOutcome",
    "check_reviewer",
    "check_reviewer_for_case",
    "citation_matches",
    "deterministic_problems",
    "finalise",
    "lost_facts",
    "review_with_model",
    "source_chunks_of",
]

REVIEW_PROMPT = ("review_item_de", "v1")
MAX_TOKENS = 500
_log = get_logger(__name__)
Sink = Callable[[ReviewItem], None]


def check_reviewer(reviewer: ModelRef, *, generator: ModelRef, datagen: ModelRef) -> None:
    """Check the family rule of the reviewer.

    The family ``gemma`` (the gating judge) is accepted: the reviewer runs reject-only.

    Raises:
        ConfigError: The reviewer's family equals the generator's or the datagen model's.
    """
    for role, other in (("generator", generator), ("datagen", datagen)):
        if reviewer.family == other.family:
            msg = f"reviewer {reviewer.id}: family '{reviewer.family}' equals the {role} family"
            raise ConfigError(msg)


def check_reviewer_for_case(reviewer_id: str, case: TestCase) -> None:
    """Refuse an external reviewer for text of a private tenant (the T5.1 guard).

    Raises:
        ConfigError: The reviewer is not a local model and the case is not ``shared_public``.
    """
    if case.tenant != PUBLIC_TENANT and provider_of(reviewer_id) not in LOCAL_PROVIDERS:
        msg = (
            f"case {case.id}: tenant {case.tenant} text must not go to the external reviewer "
            f"{reviewer_id}; use a local model"
        )
        raise ConfigError(msg)


@dataclass
class ReviewOutcome:
    """Items in input order, and the ids the reviewer failed on (an invalid answer twice)."""

    items: list[ReviewItem] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _tenant_norms(chunks: Sequence[Chunk]) -> dict[str, str]:
    keys: dict[str, set[str]] = defaultdict(set)
    for c in chunks:
        if c.citation_key:
            keys[c.tenant].add(c.citation_key)
    return {t: ", ".join(sorted(v)) for t, v in keys.items()}


def _request(case: TestCase, text: str, base: str, model: str) -> LLMRequest:
    template = PromptRegistry([PROMPT_ROOT]).get(*REVIEW_PROMPT)
    messages = template.render(
        category=case.category.value,
        question=case.question,
        base_question=base,
        answer=case.reference_answer or "",
        citation=", ".join(case.gold_citations) or "-",
        text=text,
    )
    return LLMRequest(
        role=LLMRole.JUDGE,
        model=model,
        messages=messages,
        max_tokens=MAX_TOKENS,
        prompt_id=request_prompt_id(REVIEW_PROMPT[0]),
        prompt_version=REVIEW_PROMPT[1],
        response_format="json",
    )


class _Reviewer:
    """The state of one ``review_with_model`` run: sources, questions of bases, limits."""

    def __init__(
        self,
        cases: Sequence[TestCase],
        sources: Sequence[Chunk],
        llm: LLMClient,
        model: str,
        *,
        reject_only: bool,
        concurrency: int,
        sink: Sink | None,
        done: Mapping[str, ReviewItem],
    ) -> None:
        self.llm, self.model, self.reject_only, self.sink, self.done = (
            llm,
            model,
            reject_only,
            sink,
            done,
        )
        self.by_doc: dict[str, list[Chunk]] = defaultdict(list)
        for chunk in sources:
            self.by_doc[chunk.doc_id].append(chunk)
        self.norms = _tenant_norms(sources)
        self.bases = {c.id: c.question for c in cases if c.perturbation is None}
        self.gate = asyncio.Semaphore(max(1, concurrency))

    def _text(self, case: TestCase, chunks: Sequence[Chunk]) -> str:
        if case.category is Category.UNANSWERABLE:
            return self.norms.get(case.tenant, "")
        return "\n\n".join(c.text for c in chunks)

    def _without_model(self, case: TestCase, chunks: Sequence[Chunk]) -> ReviewItem | None:
        if case.category in ATTACK_CATEGORIES:
            reason = "Angriffs- oder Prüffall: nur deterministische Prüfung"
            return deterministic_item(case, chunks, reason)
        if case.category is not Category.UNANSWERABLE and not chunks:
            return deterministic_item(case, chunks, CHUNK_MISSING)
        return None

    async def item(self, case: TestCase) -> ReviewItem | None:
        """Review one case; None when the model's answer stayed invalid."""
        if case.id in self.done:
            return self.done[case.id]
        chunks = source_chunks_of(case, self.by_doc)
        result = self._without_model(case, chunks)
        if result is None:
            check_reviewer_for_case(self.model, case)
            base = self.bases.get(case.base_id, "") if case.perturbation else ""
            request = _request(case, self._text(case, chunks), base, self.model)
            async with self.gate:
                try:
                    with private_text(private=case.tenant != PUBLIC_TENANT):
                        verdict = await self.llm.complete_json(request, ModelVerdict)
                except LLMError as exc:
                    _log.warning("review_failed", case=case.id, error=type(exc).__name__)
                    return None
            result = finalise(case, chunks, verdict, model=self.model, reject_only=self.reject_only)
        if self.sink is not None:
            self.sink(result)
        return result


async def review_with_model(
    cases: Sequence[TestCase],
    sources: Sequence[Chunk],
    llm: LLMClient,
    model: str,
    *,
    reject_only: bool = True,
    concurrency: int = 4,
    sink: Sink | None = None,
    skip: Mapping[str, ReviewItem] | None = None,
) -> ReviewOutcome:
    """Review ``cases`` with the model and apply the deterministic overrides.

    Attack and probe cases and answerable cases without a source chunk go to no model (their
    items carry ``model="deterministic"``). A perturbed variant is shown with its base question.

    Args:
        cases: The cases to review.
        sources: The corpus chunks (gold documents are looked up here).
        llm: The reviewer's client (a local provider; checked per case).
        model: Reviewer model id.
        reject_only: The reviewer must not rewrite references.
        concurrency: Requests in flight.
        sink: Called with each finished item (a resume record).
        skip: Items of an earlier run by case id; they are reused without a request.

    Returns:
        The ``ReviewOutcome``; cases whose answer stayed invalid after one repair are in ``failed``.

    Raises:
        ConfigError: An external reviewer for a private-tenant case.
        PolicyViolation, QuotaExhausted: From the client; the batch stops.
    """
    reviewer = _Reviewer(
        cases, sources, llm, model, reject_only=reject_only, concurrency=concurrency,
        sink=sink, done=dict(skip or {}),
    )  # fmt: skip
    results = await asyncio.gather(*(reviewer.item(c) for c in cases))
    outcome = ReviewOutcome()
    for case, item in zip(cases, results, strict=True):
        if item is None:
            outcome.failed.append(case.id)
        else:
            outcome.items.append(item)
    return outcome
