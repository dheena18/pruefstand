"""``OllamaChatGenerator``: the tier-2 generator on Ollama's native ``/api/chat`` (D219, D220).

Minimal in T3.2 (native body, catalogue ``options``, ``think: false``, no ``keep_alive``); T3.6
finishes it (prompt budget with the model tokenizer, citations, think-stripping rules).
"""

from typing import Any

from rag_demo.errors import GenerationError
from rag_demo.generate import OpenAICompatGenerator
from rag_demo.models import RagConfig


def build_ollama_request(messages: list[dict[str, str]], cfg: RagConfig) -> dict[str, Any]:
    """Build the ``/api/chat`` body: bare tag, ``think: false``, load-time and sampling options.

    ``options`` = the config's catalogue-checked ``num_ctx``/``top_p`` plus ``temperature``,
    ``seed`` and ``num_predict`` (= ``generation.max_tokens``) from ``generation`` (R12 N2).
    There is never a ``keep_alive`` (model loading is the orchestrator's job).

    Raises:
        GenerationError: The config has no ``generation`` section (not an Ollama profile).
    """
    gen = cfg.generation
    if gen is None:
        msg = "engine ollama needs the generation section"
        raise GenerationError(msg)
    return {
        "model": cfg.generator.model,
        "messages": messages,
        "think": cfg.generator.enable_thinking,
        "stream": False,
        "options": {
            **cfg.generator.options,
            "temperature": gen.temperature,
            "seed": gen.seed,
            "num_predict": gen.max_tokens,
        },
    }


class OllamaChatGenerator(OpenAICompatGenerator):
    """The generator for ``generator.engine: ollama``; same constructor as its base class."""

    PATH = "/api/chat"

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return build_ollama_request(messages, self._cfg)

    def _parse(self, data: dict[str, Any]) -> tuple[str, str, int, int]:
        try:
            raw = str(data["message"]["content"])
            return (
                raw,
                str(data.get("model") or self._cfg.generator.model),
                int(data.get("prompt_eval_count", 0)),
                int(data.get("eval_count", 0)),
            )
        except (KeyError, TypeError):
            msg = "generator response has an unexpected shape"
            raise GenerationError(msg) from None
