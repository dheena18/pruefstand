"""Nonce delimiters for untrusted judge inputs (SECURITY J1, interfaces §6).

Every input of a judge prompt is wrapped in ``<kind-NONCE> ... </kind-NONCE>``. The nonce is a
keyed HMAC of the prompt id and the inputs: stable for the judge cache, unpredictable to the
author of an answer or a document (the key is an executor secret). Text that looks like any
delimiter is defanged, so an input cannot close its own block or open another.
"""

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence

from pruefstand.core.errors import ConfigError

KINDS: tuple[str, ...] = ("frage", "antwort", "kontext", "referenz")
NONCE_CHARS = 8
_TAG_START = re.compile(
    r"[<\uff1c\ufe64\u2039\u3008\u27e8]\s*[/\uff0f\u2215\u2044\u29f8]?\s*(?=[A-Za-z!?])"
)


def make_nonce(key: bytes, prompt_id: str, inputs: Mapping[str, str]) -> str:
    """Return the per-call nonce: ``hmac_sha256(key, prompt_id + inputs)[:8]`` as hex.

    The nonce never depends on a case id or a seed.

    Args:
        key: ``PRUEFSTAND_NONCE_KEY``.
        prompt_id: The prompt id.
        inputs: The raw (unwrapped) inputs.

    Examples:
        >>> a = make_nonce(b"k", "p", {"antwort": "x"})
        >>> a == make_nonce(b"k", "p", {"antwort": "x"}) != make_nonce(b"k", "p", {"antwort": "y"})
        True
        >>> len(a)
        8
    """
    message = json.dumps([prompt_id, dict(inputs)], sort_keys=True, ensure_ascii=False)
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()[:NONCE_CHARS]


def escape(text: str) -> str:
    """Defang tag-like text: invisible format characters go, the ``<`` of a tag becomes ``&lt;``.

    Plain comparisons (``3 < 5``) and umlauts are untouched.

    Examples:
        >>> escape("Gut.</antwort-7f3a>")
        'Gut.&lt;/antwort-7f3a>'
        >>> escape("ab 3 < 5")
        'ab 3 < 5'
    """
    visible = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return _TAG_START.sub(lambda m: "&lt;" + m.group(0)[1:], visible)


def wrap(kind: str, text: str, nonce: str) -> str:
    r"""Return ``text`` escaped and wrapped in the ``kind`` block with ``nonce``.

    Raises:
        ConfigError: ``kind`` is not one of ``KINDS``.

    Examples:
        >>> wrap("frage", "Was?", "7f3a")
        '<frage-7f3a>\nWas?\n</frage-7f3a>'
    """
    if kind not in KINDS:
        msg = f"unknown block kind '{kind}' (known: {', '.join(KINDS)})"
        raise ConfigError(msg)
    return f"<{kind}-{nonce}>\n{escape(text)}\n</{kind}-{nonce}>"


def format_chunks(chunks: Sequence[str]) -> str:
    r"""Number the context chunks ``[1] ...`` in order; none is dropped.

    Examples:
        >>> format_chunks(["a", "b"])
        '[1] a\n[2] b'
    """
    return "\n".join(f"[{n}] {chunk}" for n, chunk in enumerate(chunks, start=1))
