"""Pass 2 of ``scripts/generate_qa.py``: re-checks of cached candidates, no datagen call (T4.2).

The deterministic checks need no model. The optional judge check asks the LOCAL judge (day mode,
``pruefstand-lock``) whether the reference answer is supported by the source text; it never
writes or rewrites a reference (D330) and never uses an external provider. The filters of T4.3
(``check_support``, overlap, near-duplicates) decide what is kept; this pass only reports.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from pruefstand.core.citations import extract_citations, parse_one
from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.dataset.evidence import normalise_text
from pruefstand.dataset.generate_units import PROMPT_ROOT
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.prompts import PromptRegistry

VALIDATE_PROMPT = ("qa_validate_de", "v1")
_log = get_logger(__name__)


class ValidationRow(BaseModel):
    """Result of pass 2 for one candidate (``problems`` empty = nothing found)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    problems: tuple[str, ...]
    judge_supported: bool | None


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    supported: bool
    reason: str = ""


def _citation_problems(c: QACandidate, chunks: Sequence[Chunk]) -> list[str]:
    if not c.citation:
        return []
    found = extract_citations(c.citation)
    if not found:
        return ["citation_unparsed"]
    for chunk in chunks:
        key = parse_one(chunk.citation_key) if chunk.citation_key else None
        if key and not any(
            (f.kind, f.number, f.law) == (key.kind, key.number, key.law) for f in found
        ):
            return ["citation_mismatch"]
    return []


def check_candidate(c: QACandidate, chunks: Mapping[str, Chunk]) -> tuple[str, ...]:
    """Run the deterministic checks of one candidate.

    Returns:
        Problem names: ``chunk_missing``, ``answer_empty``, ``citation_unparsed``,
        ``citation_mismatch`` (the citation names another paragraph than the source chunks),
        ``evidence_missing``, ``evidence_not_in_chunk``. Empty when all checks pass.
    """
    sources = [chunks[i] for i in (c.chunk_id, *c.extra_chunk_ids) if i in chunks]
    if len(sources) != 1 + len(c.extra_chunk_ids):
        return ("chunk_missing",)
    problems = ["answer_empty"] if not c.answer.strip() else []
    problems += _citation_problems(c, sources)
    if c.evidence_span is None:
        problems.append("evidence_missing")
    elif not any(c.evidence_span in normalise_text(s.text) for s in sources):
        problems.append("evidence_not_in_chunk")
    return tuple(problems)


async def _judge(
    c: QACandidate, sources: Sequence[Chunk], llm: LLMClient, model: str
) -> bool | None:
    template = PromptRegistry([PROMPT_ROOT]).get(*VALIDATE_PROMPT)
    text = "\n\n".join(s.text for s in sources)
    request = LLMRequest(
        role=LLMRole.JUDGE,
        model=model,
        messages=template.render(question=c.question, answer=c.answer, text=text),
        max_tokens=200,
        prompt_id=VALIDATE_PROMPT[0],
        prompt_version=VALIDATE_PROMPT[1],
        response_format="json",
    )
    try:
        return (await llm.complete_json(request, _Verdict)).supported
    except LLMError as exc:
        _log.warning("validate_judge_failed", error=type(exc).__name__)
        return None


async def validate_candidates(
    cands: Sequence[QACandidate],
    chunks: Mapping[str, Chunk],
    judge: LLMClient | None,
    judge_model: str | None,
) -> list[ValidationRow]:
    """Check every candidate; with a judge, also ask whether the answer is supported.

    Args:
        cands: Cached candidates.
        chunks: Their source chunks by id.
        judge: Client of the LOCAL judge model, or None for the deterministic checks only.
        judge_model: The judge's model id (``ollama/...`` or ``openai_compatible_local/...``).

    Returns:
        One row per candidate; a judge failure is ``judge_error`` with ``judge_supported=None``.

    Raises:
        ConfigError: A judge is given without a local model id.
    """
    if judge is not None and (
        judge_model is None or provider_of(judge_model) not in LOCAL_PROVIDERS
    ):
        msg = "the pass-2 judge must be a local model (ollama/ or openai_compatible_local/, D330)"
        raise ConfigError(msg)
    rows: list[ValidationRow] = []
    for c in cands:
        problems = list(check_candidate(c, chunks))
        verdict: bool | None = None
        if judge is not None and judge_model is not None and "chunk_missing" not in problems:
            sources = [chunks[i] for i in (c.chunk_id, *c.extra_chunk_ids)]
            verdict = await _judge(c, sources, judge, judge_model)
            if verdict is None:
                problems.append("judge_error")
            elif not verdict:
                problems.append("judge_unsupported")
        rows.append(
            ValidationRow(chunk_id=c.chunk_id, problems=tuple(problems), judge_supported=verdict)
        )
    return rows
