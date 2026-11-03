"""Pure helpers of the T3.1b model benchmark: throughput, JSON validity, nDCG, bootstrap, redaction.

Everything here is deterministic and offline; ``bench.py`` and ``embed_bench.py`` feed it measured
numbers.
"""

import json
import re
from collections.abc import Mapping, Sequence

import numpy as np

CI = tuple[float, float, float]  # (mean, lower, upper)
_PATH_DATA = re.compile(r"/data/[\w.-]+")
_PATH_HOME = re.compile(r"/home/[\w.-]+")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")


def tok_per_s(tokens: int, seconds: float) -> float:
    """Return tokens per second, 0.0 when no time elapsed.

    >>> tok_per_s(100, 2.0)
    50.0
    """
    return tokens / seconds if seconds > 0 else 0.0


def split_prefill_decode(
    prompt_tokens: int, decode_tokens: int, ttft_s: float, total_s: float
) -> tuple[float, float]:
    """Split one streamed call into (prefill tok/s, decode tok/s).

    The first token arrives after the prefill (``ttft_s``); the remaining ``decode_tokens - 1``
    tokens take ``total_s - ttft_s``.

    >>> split_prefill_decode(3000, 101, 1.5, 3.5)
    (2000.0, 50.0)
    """
    return tok_per_s(prompt_tokens, ttft_s), tok_per_s(max(decode_tokens - 1, 0), total_s - ttft_s)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile ``q`` (0-100); 0.0 for an empty list.

    >>> percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)
    3.0
    """
    return float(np.percentile(np.asarray(values, dtype=float), q)) if values else 0.0


def json_valid(text: str) -> bool:
    """Judge-format validity: object with a string ``reason`` and an integer ``score``.

    >>> json_valid('{"reason": "x", "score": 1}'), json_valid('{"score": 1}')
    (True, False)
    """
    try:
        obj = json.loads(text)
    except ValueError:
        return False
    if not isinstance(obj, dict):
        return False
    score = obj.get("score")
    return (
        isinstance(obj.get("reason"), str)
        and isinstance(score, int)
        and not isinstance(score, bool)
    )


def validity_rate(texts: Sequence[str]) -> float:
    """Share of ``texts`` that are valid judge JSON (0.0 for an empty list)."""
    return sum(json_valid(t) for t in texts) / len(texts) if texts else 0.0


def ndcg_at_k(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """Binary-gain nDCG@k; gold at rank 1 gives 1.0, at rank 3 gives 0.5.

    >>> ndcg_at_k(["x", "y", "a"], {"a"}, 10)
    0.5
    """
    dcg = sum(1.0 / np.log2(i + 2) for i, doc in enumerate(ranked[:k]) if doc in gold)
    ideal = sum(1.0 / np.log2(i + 2) for i in range(min(len(gold), k)))
    return float(dcg / ideal) if ideal else 0.0


def bootstrap_ci(scores: Sequence[float], n: int = 2000, seed: int = 0, alpha: float = 0.05) -> CI:
    """Mean and 95 % percentile bootstrap interval (2 000 resamples, fixed seed) of ``scores``."""
    arr = np.asarray(scores, dtype=float)
    if arr.size == 0:
        return (0.0, 0.0, 0.0)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, arr.size, size=(n, arr.size))].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(arr.mean()), float(lo), float(hi))


def pick(a: CI, b: CI, cost_a: float, cost_b: float) -> str:
    """Return ``"a"`` or ``"b"``.

    The better mean when the CIs do not overlap, else the cheaper one (less VRAM).
    """
    if a[1] > b[2]:
        return "a"
    if b[1] > a[2]:
        return "b"
    return "a" if cost_a <= cost_b else "b"


def redact(text: str, extra: Mapping[str, str] | None = None) -> str:
    """Replace cluster paths, home paths, IPv4 addresses and the given words by placeholders."""
    out = _PATH_DATA.sub("<models-dir>", text)
    out = _PATH_HOME.sub("<home>", out)
    out = _IPV4.sub("<ip>", out)
    for word, placeholder in (extra or {}).items():
        out = out.replace(word, placeholder)
    return out
