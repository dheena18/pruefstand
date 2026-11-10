"""Strict JSON reading for ``llm-proxy`` (D1070): see the body exactly as Ollama's Go decoder will.

Go's ``encoding/json`` matches struct field names case-insensitively and lets the last duplicate
win, so ``{"model": "<gen>", "MODEL": "<judge>"}`` would reach the judge. Every JSON object at any
depth is therefore refused when two keys are equal after NFKC + Unicode casefold (exact duplicates
included), ``NaN``/``Infinity`` are refused, and the top level may hold only the exact ASCII keys
of its route. The forwarded body is written back ASCII-only (lone surrogates become escapes).
"""

import json
import math
import unicodedata

TOP_LEVEL_KEYS: dict[str, frozenset[str]] = {
    "generator": frozenset(
        {"model", "messages", "stream", "format", "tools", "think", "options", "keep_alive"}
    ),
    "embed": frozenset({"model", "input", "truncate", "dimensions", "options", "keep_alive"}),
}


class StrictJSONError(ValueError):
    """The body is not a JSON object the proxy can judge unambiguously."""


def fold(key: str) -> str:
    """The comparison form of a key: NFKC, then Unicode casefold (Kelvin sign + EY is key)."""
    return unicodedata.normalize("NFKC", key).casefold()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    for key, _ in pairs:
        folded = fold(key)
        if folded in seen:
            msg = "duplicate or case-colliding key"
            raise StrictJSONError(msg)
        seen.add(folded)
    return dict(pairs)


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        msg = "number out of range"
        raise StrictJSONError(msg)
    return value


def _no_constant(name: str) -> object:
    msg = f"JSON constant {name} not allowed"
    raise StrictJSONError(msg)


def load_object(body: bytes, role: str) -> dict[str, object]:
    """Parse ``body`` strictly and check its top-level keys against ``role``'s allow-list.

    Raises:
        StrictJSONError: not UTF-8 JSON, not an object, a key collision at any depth, NaN or
            Infinity, or a top-level key outside the route's exact ASCII allow-list.
    """
    try:
        data = json.loads(
            body, object_pairs_hook=_pairs, parse_constant=_no_constant, parse_float=_finite
        )
    except StrictJSONError:
        raise
    except (ValueError, UnicodeDecodeError) as err:
        msg = "body is not JSON"
        raise StrictJSONError(msg) from err
    if not isinstance(data, dict):
        msg = "body is not a JSON object"
        raise StrictJSONError(msg)
    allowed = TOP_LEVEL_KEYS[role]
    extra = sorted(k for k in data if k not in allowed)
    if extra:
        msg = f"field not allowed: {extra[0]!a}"
        raise StrictJSONError(msg)
    return data


def dump(data: object) -> bytes:
    """Serialise for the upstream: ASCII-only, no NaN (a lone surrogate becomes an escape).

    Raises:
        StrictJSONError: the data cannot be written (e.g. a non-finite number), so a 403.
    """
    try:
        return json.dumps(data, ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError) as err:
        msg = "body cannot be forwarded"
        raise StrictJSONError(msg) from err
