"""Support check and near-duplicate filter (T4.3, interfaces §14).

``check_support`` asks a second model, of ANOTHER family than the one that wrote the candidate,
whether the source chunk supports the reference answer; ``dedupe`` removes questions whose
embeddings are near-identical. ``dataset.filters`` re-exports all public filters.
"""

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, field_validator

from pruefstand.core.errors import (
    ConfigError,
    DatasetError,
    LLMError,
    PolicyViolation,
    QuotaExhausted,
)
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import FilterResult, QACandidate
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.dataset.generate_units import PROMPT_ROOT
from pruefstand.dataset.to_case import case_id_of
from pruefstand.llm.client import LLMClient
from pruefstand.llm.families import family_of
from pruefstand.llm.prompts import PromptRegistry

SUPPORT_PROMPT = ("support_check_de", "v1")
Embedder = Callable[[Sequence[str]], NDArray[np.float32]]
_log = get_logger(__name__)
_TAG = re.compile(r"</?\s*abschnitt", re.IGNORECASE)


class _Support(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: Literal[0, 1]
    reason: str | None = None

    @field_validator("score", mode="before")
    @classmethod
    def _not_a_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            msg = "score must be 0 or 1, not a boolean"
            raise ValueError(msg)  # noqa: TRY004  (pydantic wants ValueError)
        return value


def check_support_family(support_model: str, generator_model: str) -> None:
    """Refuse a support model of the family that wrote the candidates.

    Raises:
        ConfigError: Both ids have the same family (or one matches no family).

    Examples:
        >>> check_support_family("ollama/gemma3:12b", "github/openai/gpt-4.1-mini")
    """
    if family_of(support_model) == family_of(generator_model):
        msg = f"support model {support_model} has the family of the generator {generator_model}"
        raise ConfigError(msg)


def prompt_fingerprint() -> str:
    """Name and sha256 of the support prompt text (part of the verdict key)."""
    path = PROMPT_ROOT / f"{SUPPORT_PROMPT[0]}_{SUPPORT_PROMPT[1]}.txt"
    text = path.read_text(encoding="utf-8")
    return f"{path.stem}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def support_key(c: QACandidate, chunks: Sequence[Chunk], model: str) -> str:
    """Key of a support verdict: everything the verdict depends on.

    A hash of the candidate id, question, answer, the texts of all its chunks, the support prompt
    (name and text hash) and the support model, so a verdict is reused only for the very same
    question.
    """
    payload = [
        case_id_of(c), c.question, c.answer, [x.text for x in chunks], prompt_fingerprint(), model,
    ]  # fmt: skip
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def _wrap(chunks: Sequence[Chunk]) -> str:
    """Chunk texts as ``<abschnitt>`` data blocks (a closing tag inside the text is defused)."""
    safe = [_TAG.sub(lambda m: m.group(0).replace("<", "< "), c.text) for c in chunks]
    return "\n".join(f"<abschnitt>\n{text}\n</abschnitt>" for text in safe)


async def check_support(
    c: QACandidate,
    chunk: Chunk,
    llm: LLMClient,
    model: str,
    *,
    extra: Sequence[Chunk] = (),
    generator_model: str | None = None,
) -> FilterResult:
    """Ask the support model whether the chunk(s) support the reference answer.

    Args:
        c: The candidate.
        chunk: Its gold chunk.
        llm: Client of the support model (local A40 model or a GitHub Models id, role DATAGEN).
        model: The support model id.
        extra: The second chunk of a pair.
        generator_model: The model that wrote the candidate; its family must differ.

    Returns:
        Kept when the model answers ``score`` 1; ``unsupported`` for 0; ``judge_error`` when the
        answer stays invalid after the repair or the call fails.

    Raises:
        ConfigError: ``generator_model`` has the support model's family.
        QuotaExhausted: The provider quota is used up (the batch must stop).
        BudgetExceeded: The request cap is reached.
        PolicyViolation: The provider policy refuses the request.
    """
    if generator_model is not None:
        check_support_family(model, generator_model)
    template = PromptRegistry([PROMPT_ROOT]).get(*SUPPORT_PROMPT)
    request = LLMRequest(
        role=LLMRole.DATAGEN,
        model=model,
        messages=template.render(question=c.question, answer=c.answer, text=_wrap([chunk, *extra])),
        max_tokens=300,
        prompt_id=SUPPORT_PROMPT[0],
        prompt_version=SUPPORT_PROMPT[1],
        response_format="json",
    )
    try:
        verdict = await llm.complete_json(request, _Support)
    except (QuotaExhausted, PolicyViolation):
        raise
    except LLMError as exc:
        _log.warning("support_check_failed", error=type(exc).__name__, status=exc.status)
        return FilterResult(kept=False, reasons=("judge_error",))
    if verdict.score == 1:
        return FilterResult(kept=True, reasons=())
    return FilterResult(kept=False, reasons=("unsupported",))


def dedupe_report(
    cands: Sequence[QACandidate], embed: Embedder, max_sim: float = 0.9
) -> tuple[list[QACandidate], list[QACandidate]]:
    """Greedy near-duplicate filter; returns ``(kept, dropped)``, both ordered by stable id.

    Questions are embedded; a candidate is dropped when its cosine to an already kept one is at
    least ``max_sim``. Candidates are visited in the order of their stable ids, so the result does
    not depend on the input order.

    Raises:
        DatasetError: ``embed`` returns the wrong shape or a zero vector.
    """
    ordered = sorted(cands, key=case_id_of)
    if not ordered:
        return [], []
    vectors = np.asarray(embed([c.question for c in ordered]), dtype=np.float64)
    if vectors.ndim != 2 or vectors.shape[0] != len(ordered):
        msg = f"embedding function returned shape {vectors.shape} for {len(ordered)} questions"
        raise DatasetError(msg)
    norms = np.linalg.norm(vectors, axis=1)
    if not np.all(norms > 0):
        msg = "embedding function returned a zero vector"
        raise DatasetError(msg)
    unit = vectors / norms[:, None]
    kept: list[int] = []
    dropped: list[int] = []
    for i in range(len(ordered)):
        if kept and float(np.max(unit[kept] @ unit[i])) >= max_sim:
            dropped.append(i)
        else:
            kept.append(i)
    return [ordered[i] for i in kept], [ordered[i] for i in dropped]


def dedupe(
    cands: Sequence[QACandidate], embed: Embedder, max_sim: float = 0.9
) -> list[QACandidate]:
    """Remove near-duplicate questions (cosine >= ``max_sim`` to a kept one).

    Args:
        cands: Candidates in any order.
        embed: Maps question texts to an array of shape ``(n, dim)``.
        max_sim: Cosine from which a question counts as a duplicate.

    Returns:
        The kept candidates ordered by stable id (deterministic for any input order).

    Raises:
        DatasetError: ``embed`` returns the wrong shape or a zero vector.

    Examples:
        >>> def embed(texts):
        ...     table = {"a": [1.0, 0.0], "b": [0.99, 0.1], "c": [0.0, 1.0]}
        ...     return np.array([table[t] for t in texts], dtype=np.float32)
        >>> mk = lambda q: QACandidate(question=q, answer="x", citation=None, chunk_id="d#0",
        ...                            prompt_version="qa_factual_de_v1")
        >>> sorted(c.question for c in dedupe([mk("a"), mk("b"), mk("c")], embed))
        ['a', 'c']
    """
    return dedupe_report(cands, embed, max_sim)[0]
