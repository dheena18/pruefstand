"""Pure extraction of the first JSON object from model output (fences, prose around it)."""


def extract_json_object(text: str) -> str | None:
    r"""Return the first complete ``{...}`` object in ``text``, or None.

    Code fences and surrounding prose are ignored; braces inside JSON strings do not count.

    Args:
        text: Raw model output.

    Returns:
        The object source text, or None when no balanced object exists.

    Examples:
        >>> extract_json_object('```json\\n{"a": {"b": 1}}\\n```')
        '{"a": {"b": 1}}'
        >>> extract_json_object("kein JSON") is None
        True
    """
    start = text.find("{")
    while start != -1:
        end = _object_end(text, start)
        if end is not None:
            return text[start : end + 1]
        start = text.find("{", start + 1)
    return None


def _object_end(text: str, start: int) -> int | None:
    """Return the index of the brace closing the object that opens at ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None
