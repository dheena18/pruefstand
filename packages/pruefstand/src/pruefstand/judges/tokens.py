"""Token estimate and input cap of a judge (round 9 X3.9).

The cap of a judge is its context window minus 1 024 tokens: the catalogue ``options.num_ctx`` for
an Ollama judge, the documented input limit of ``llm/quotas.yaml`` for a GitHub Models judge.
No tokenizer file is available offline, so the count is a conservative estimate (letters 0.4,
digits, punctuation and non-ASCII one, long unbroken runs one per character): it over-counts
German prose and truncates earlier than a real tokenizer would, never later. After each call the
judge also compares the provider's reported prompt tokens with the window (``judge_window``). The
catalogue tokenizer (``tokenizer.source``) is a follow-up: it needs a new dependency.
"""

import math

from pruefstand.core.errors import ConfigError
from pruefstand.llm.costs import quota_for
from pruefstand.llm.policy import provider_of
from pruefstand.llm.providers import catalogue_options

HEADROOM_TOKENS = 1_024
DEFAULT_WINDOW_TOKENS = 8_192
"""Window assumed for a judge whose provider documents none (a local OpenAI-compatible server)."""
_LETTER_TOKENS = 0.4  # one token per 2.5 letters of an ordinary word (conservative)
_SPACE_TOKENS = 0.25
_LONG_WORD = (
    12  # longer unbroken runs (hex, base64, identifiers, URLs) cost one token per character
)


def _word_tokens(word: str) -> float:
    if len(word) > _LONG_WORD:
        return float(len(word))
    total = 0.0
    for char in word:
        plain = char.isascii() and char.isalpha()
        total += _LETTER_TOKENS if plain else 1.0  # digits, punctuation, pipes, non-ASCII
    return max(1.0, total)  # every word costs at least one token


def estimate_tokens(text: str) -> int:
    r"""Return a conservative (high) token count of ``text``.

    Letters of an ordinary word count 0.4 token but a word never less than one, a newline one, any
    other space 0.25, everything else (digits, punctuation, table pipes, non-ASCII characters) one
    token each, and an unbroken run of more than 12 characters (hex, base64) one per character.
    This over-counts German prose and does not under-count number-, hex-, table- or
    single-letter-word-dense text.

    Examples:
        >>> estimate_tokens(""), estimate_tokens("abc"), estimate_tokens("4711")
        (0, 2, 4)
        >>> estimate_tokens("Kündigung")
        5
        >>> estimate_tokens("a" * 40), estimate_tokens("x\n" * 10)
        (40, 20)
    """
    words = text.split()
    gaps = len(text) - sum(len(w) for w in words)
    newlines = text.count("\n")
    return math.ceil(
        sum(_word_tokens(w) for w in words) + newlines + (gaps - newlines) * _SPACE_TOKENS
    )


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


def judge_window(model_id: str) -> int | None:
    """Return ``num_ctx - num_predict`` of an Ollama judge (the room for the prompt), else None."""
    if provider_of(model_id) != "ollama":
        return None
    options = catalogue_options(model_id)
    return int(options["num_ctx"]) - int(options["num_predict"])
