"""Token counting for the ``truncated_chunks`` counter (DEV11-21).

Ollama does not report per-input truncation, so the encoder counts tokens itself: with the
embedding model's ``tokenizer.json`` (HF ``tokenizers``, baked into the image at build time) when
one is configured, else with a word-and-punctuation lower bound.
"""

import re
from collections.abc import Callable
from pathlib import Path

from rag_demo.errors import ConfigError

TokenCounter = Callable[[str], int]
_WORD = re.compile(r"\w+|[^\w\s]")


def approx_token_count(text: str) -> int:
    """Count words and punctuation marks: a lower bound of the model's token count.

    Examples:
        >>> approx_token_count("Frist (§ 622)")
        5
    """
    return len(_WORD.findall(text))


def load_token_counter(path: Path) -> TokenCounter:
    """Load a Hugging Face ``tokenizer.json`` and return a function that counts tokens.

    Args:
        path: The pinned ``tokenizer.json`` of the embedding model.

    Returns:
        ``count(text)`` including the special tokens the model adds to every input.

    Raises:
        ConfigError: The file is missing or not a tokenizer.
    """
    from tokenizers import Tokenizer  # noqa: PLC0415  (heavy import, only needed when configured)

    if not path.is_file():
        msg = f"embedding tokenizer file {path} does not exist"
        raise ConfigError(msg)
    try:
        tokenizer = Tokenizer.from_file(str(path))
    except Exception:
        msg = f"embedding tokenizer file {path} is not a valid tokenizer.json"
        raise ConfigError(msg) from None
    return lambda text: len(tokenizer.encode(text).ids)
