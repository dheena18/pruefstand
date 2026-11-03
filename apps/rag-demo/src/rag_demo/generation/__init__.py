"""Answer generation of rag-demo: prompt files, the two chat clients, guards and the generators."""

from rag_demo.generation.generator import ChatGenerator, OllamaChatGenerator, OpenAICompatGenerator
from rag_demo.generation.postprocess import (
    REFUSAL,
    REFUSAL_EN,
    apply_output_guard,
    extract_citations,
    is_refusal,
    strip_think,
)
from rag_demo.generation.prompting import (
    build_prompt,
    count_truncated,
    load_prompt,
    prompt_hits,
    truncate_to_tokens,
)

__all__ = [
    "REFUSAL",
    "REFUSAL_EN",
    "ChatGenerator",
    "OllamaChatGenerator",
    "OpenAICompatGenerator",
    "apply_output_guard",
    "build_prompt",
    "count_truncated",
    "extract_citations",
    "is_refusal",
    "load_prompt",
    "prompt_hits",
    "strip_think",
    "truncate_to_tokens",
]
