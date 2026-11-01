"""Pure extraction of the first JSON object from model output (fences, prose around it)."""

import json

MAX_SCAN_CHARS = 256 * 1024
MAX_CANDIDATES = 1000
_DECODER = json.JSONDecoder()


def extract_json_object(text: str) -> str | None:
    r"""Return the first valid ``{...}`` JSON object in ``text``, or None.

    Code fences and surrounding prose are ignored. Every ``{`` is tried with
    ``json.JSONDecoder.raw_decode``, so ``{Platzhalter}`` does not hide a later object, and only
    text that really parses is returned. Only the first 256 KiB are scanned and at most 1000
    candidates are tried, so adversarial output costs linear time.

    Args:
        text: Raw model output.

    Returns:
        The object source text, or None when no valid object exists in the scanned part.

    Examples:
        >>> extract_json_object('```json\n{"a": {"b": 1}}\n```')
        '{"a": {"b": 1}}'
        >>> extract_json_object('Beispiel {Platzhalter} und {"a":1}')
        '{"a":1}'
        >>> extract_json_object("kein JSON") is None
        True
    """
    window = text[:MAX_SCAN_CHARS]
    start = window.find("{")
    for _ in range(MAX_CANDIDATES):
        if start == -1:
            return None
        try:
            obj, end = _DECODER.raw_decode(window, start)
        except (ValueError, RecursionError):
            start = window.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            return window[start:end]
        start = window.find("{", start + 1)
    return None
