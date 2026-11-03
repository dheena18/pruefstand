"""Token estimate and input cap of a judge (round 9 X3.9).

The cap of a judge is its context window minus 1 024 tokens: the catalogue ``options.num_ctx`` for
an Ollama judge, the documented input limit of ``llm/quotas.yaml`` for a GitHub Models judge.
No tokenizer file is available offline, so the count is a conservative estimate (digits one token
each, other ASCII 0.4, non-ASCII one): it over-counts German prose and truncates earlier than a
real tokenizer would, never later. The catalogue tokenizer (``tokenizer.source``) is a follow-up:
it needs a new dependency.
"""

import math

from pruefstand.core.errors import ConfigError
from pruefstand.llm.costs import quota_for
from pruefstand.llm.policy import provider_of
from pruefstand.llm.providers import catalogue_options

HEADROOM_TOKENS = 1_024
DEFAULT_WINDOW_TOKENS = 8_192
"""Window assumed for a judge whose provider documents none (a local OpenAI-compatible server)."""
_ASCII_CHAR_TOKENS = 0.4  # one token per 2.5 ordinary ASCII characters (conservative)


def estimate_tokens(text: str) -> int:
    """Return a conservative (high) token count of ``text``.

    Digits count one token each (Gemma splits numbers into single digits, so amounts, file
    numbers and tables are token-dense), a non-ASCII character one token, any other character
    0.4 token. This over-counts German prose and never under-counts number-dense text.

    Examples:
        >>> estimate_tokens(""), estimate_tokens("abc"), estimate_tokens("4711")
        (0, 2, 4)
        >>> estimate_tokens("Kündigung")
        5
    """
    digits = sum(c.isdigit() for c in text)
    other = text.encode("ascii", "ignore").decode().__len__() - digits
    non_ascii = len(text) - len(text.encode("ascii", "ignore"))
    return math.ceil(digits + non_ascii + other * _ASCII_CHAR_TOKENS)


def input_cap(model_id: str) -> int:
    """Return the input cap of the judge ``model_id``: its context window minus 1 024 tokens.

    Args:
        model_id: ``ollama/<tag>``, ``github/<model>`` or another provider id.

    Returns:
        The cap in tokens. An Ollama judge reads the catalogue ``num_ctx`` (12 288 gives 11 264);
        a GitHub Models judge the ``tokens_per_request`` of its quota entry; any other judge
        ``DEFAULT_WINDOW_TOKENS - 1 024``.

    Raises:
        ConfigError: An Ollama judge is not in the catalogue, or ``model_id`` is malformed.
    """
    provider = provider_of(model_id)
    if provider == "ollama":
        window = int(catalogue_options(model_id)["num_ctx"])
    else:
        quota = quota_for(model_id) if provider == "github" else None
        window = quota.tokens_per_request if quota is not None else DEFAULT_WINDOW_TOKENS
    cap = window - HEADROOM_TOKENS
    if cap <= 0:
        msg = f"the context window of {model_id} ({window}) leaves no room for an input"
        raise ConfigError(msg)
    return cap
