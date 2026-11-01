"""One scanner for secret-looking text; cassette recording refuses whatever it finds."""

import json
import re
from collections.abc import Iterator
from urllib.parse import unquote

from pruefstand.core.errors import LLMError

SECRET_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{8,}"
    r"|gh[pousr]_|github_pat_"
    r"|(?<![A-Za-z0-9])hf_[A-Za-z0-9]{8,}"
    r"|Bearer\s+\S{8,}"
    r"|eyJ[A-Za-z0-9_-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-"
    r"|glpat-"
    r"|AIza[0-9A-Za-z_-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?:password|passwd|secret)\s*=\s*\S{4,}",
    re.IGNORECASE,
)
_MAX_DEPTH = 3


def _views(text: str, depth: int = 0) -> Iterator[str]:
    """Yield the raw text, its URL-decoded form and every string inside JSON found in it."""
    yield text
    decoded = unquote(text)
    if decoded != text:
        yield decoded
    if depth >= _MAX_DEPTH:
        return
    stripped = text.lstrip()
    if stripped[:1] not in {"{", "["}:
        return
    try:
        data = json.loads(text)
    except ValueError:
        return
    yield from _json_strings(data, depth + 1)


def _json_strings(node: object, depth: int) -> Iterator[str]:
    if isinstance(node, str):
        yield from _views(node, depth)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _json_strings(key, depth)
            yield from _json_strings(value, depth)
    elif isinstance(node, list):
        for item in node:
            yield from _json_strings(item, depth)


def assert_no_secrets(text: str) -> None:
    r"""Refuse text that looks like it holds a token, key or credential.

    The raw text, its URL-decoded form and every string inside JSON (so ``Bearer\\t<token>``
    is seen with its real tab) are matched case-insensitively.

    Args:
        text: Anything about to be written to a cassette (URL, headers, body, JSON file).

    Raises:
        LLMError: ``text`` matches ``SECRET_PATTERN``; the message never repeats the match.

    Examples:
        >>> assert_no_secrets("Die Kündigung muss schriftlich erfolgen.")
        >>> assert_no_secrets("Authorization: Bearer abcdefgh12345")
        Traceback (most recent call last):
        ...
        pruefstand.core.errors.LLMError: recording refused: the text looks like a secret
    """
    if any(SECRET_PATTERN.search(view) for view in _views(text)):
        msg = "recording refused: the text looks like a secret"
        raise LLMError(msg, transient=False)
