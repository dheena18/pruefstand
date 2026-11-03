"""The two generators: ``OpenAICompatGenerator`` (tier 1) and ``OllamaChatGenerator`` (tier 2).

They share prompting, the prompt budget, refusal detection, citation extraction and the
``<think>`` strip; only the wire format (the chat client) differs (T3.6).
"""

import logging

import httpx

from rag_demo.generation.budget import (
    count_prompt_tokens,
    fit_hits,
    is_overflow,
    prompt_budget,
)
from rag_demo.generation.llm_client import (
    ChatClient,
    OllamaChatClient,
    OpenAICompatClient,
)
from rag_demo.generation.postprocess import (
    REFUSAL,
    REFUSAL_EN,
    apply_output_guard,
    detect_language,
    extract_citations,
    is_refusal,
    strip_think,
)
from rag_demo.generation.prompting import build_prompt, count_truncated
from rag_demo.index.tokens import TokenCounter
from rag_demo.models import GenOutput, Hit, RagConfig, Stats

_log = logging.getLogger(__name__)


class ChatGenerator:
    """Build the prompt, call the chat client, post-process the answer.

    Args:
        cfg: Active configuration.
        base_url: Server base URL, e.g. ``http://llm:8080`` or ``http://llm-proxy:11500``.
        stats: Runtime counters (``think_stripped``, ``truncated_chunks``, ``prompt_overflow``).
        client: Optional ``httpx.AsyncClient`` (tests).
        timeout_s: Request timeout; must allow queueing behind other requests.
        count_tokens: Counts tokens with the generator's own tokenizer (Ollama budget and the
            ``prompt_overflow`` check); ``None`` disables both.
    """

    CLIENT: type[OpenAICompatClient] | type[OllamaChatClient] = OpenAICompatClient
    CHECK_OVERFLOW = False

    def __init__(
        self,
        cfg: RagConfig,
        base_url: str,
        *,
        stats: Stats,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 180.0,
        count_tokens: TokenCounter | None = None,
    ) -> None:
        self._cfg = cfg
        self._stats = stats
        self.timeout_s = timeout_s
        self._count = count_tokens
        self._chat: ChatClient = self.CLIENT(cfg, base_url, client=client, timeout_s=timeout_s)

    def _refused(self, question: str) -> GenOutput:
        """The refusal for an empty retrieval: no model call, in the language of the question."""
        english = detect_language(question) == "en"
        return GenOutput(
            answer=REFUSAL_EN if english else REFUSAL,
            citations=[],
            refused=True,
            model=self._cfg.generator.model,
            prompt_tokens=0,
            completion_tokens=0,
            prompt_chunk_ids=[],
        )

    def _check_overflow(self, messages: list[dict[str, str]], reported: int) -> None:
        budget = prompt_budget(self._cfg)
        if budget is None:
            return
        local = count_prompt_tokens(messages, self._count, self._cfg) if self._count else None
        _log.info("prompt tokens local=%s reported=%d budget=%d", local, reported, budget)
        if is_overflow(reported, local, budget):
            self._stats.prompt_overflow += 1
            _log.warning("prompt_overflow: local=%s reported=%d budget=%d", local, reported, budget)

    async def answer(self, question: str, hits: list[Hit]) -> GenOutput:
        """Generate the answer for ``question`` from ``hits``.

        Args:
            question: The user's question.
            hits: Retrieved chunks in rank order; all that fit the prompt budget enter the prompt.

        Returns:
            The post-processed answer (``<think>`` stripped, output guard applied), its norm
            citations (empty when refused), the ``refused`` flag, usage and the ids of the chunks
            that entered the prompt. An empty retrieval is refused without a model call.

        Raises:
            GenerationError: Unreachable server, HTTP error, timeout or unexpected response shape.
        """
        if not hits:
            return self._refused(question)
        used = fit_hits(question, hits, self._cfg, self._count)
        messages = build_prompt(question, used, self._cfg)
        self._stats.truncated_chunks += count_truncated(used, self._cfg)
        reply = await self._chat.chat(messages)
        if self.CHECK_OVERFLOW:
            self._check_overflow(messages, reply.prompt_tokens)
        text, stripped = strip_think(reply.text)
        self._stats.think_stripped += stripped
        answer = apply_output_guard(text, messages[0]["content"], self._cfg)
        refused = is_refusal(answer)
        return GenOutput(
            answer=answer,
            citations=[] if refused else extract_citations(answer),
            refused=refused,
            model=reply.model,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            prompt_chunk_ids=[h.chunk_id for h in used],
        )


class OpenAICompatGenerator(ChatGenerator):
    """Tier 1: llama.cpp over the OpenAI-compatible ``/v1/chat/completions``."""

    CLIENT = OpenAICompatClient


class OllamaChatGenerator(ChatGenerator):
    """Tier 2: Ollama native ``/api/chat``: ``think: false``, catalogue options, no keep_alive."""

    CLIENT = OllamaChatClient
    CHECK_OVERFLOW = True
