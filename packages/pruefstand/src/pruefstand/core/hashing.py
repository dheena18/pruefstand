"""Canonical hashing of arbitrary parts (interfaces §2); the primitive behind all fingerprints."""

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import PurePath

from pydantic import BaseModel


def _canonical(obj: object) -> object:
    """Convert ``obj`` to JSON-ready data following the encoding rules of ``stable_hash``."""
    if obj is None or isinstance(obj, str | int | float):  # bool is an int
        return obj
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Mapping):
        out: dict[str, object] = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                msg = f"stable_hash: mapping key {key!r} is not a str"
                raise TypeError(msg)
            out[key] = _canonical(value)
        return out
    if isinstance(obj, list | tuple):
        return [_canonical(item) for item in obj]
    return _convert_leaf(obj)


def _convert_leaf(obj: object) -> object:
    if isinstance(obj, bytes):
        return {"__bytes__": obj.hex()}
    if isinstance(obj, PurePath):
        return str(obj)
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    msg = f"stable_hash: cannot hash an object of type {type(obj).__name__}"
    raise TypeError(msg)


def stable_hash(*parts: object) -> str:
    """Hash ``parts`` into 16 hex characters, stable across processes and platforms.

    The digest is ``sha256`` over the canonical JSON of the **list** of parts (so
    ``stable_hash("a", "b") != stable_hash("ab")``), cut to 16 characters. JSON uses sorted keys,
    separators ``(",", ":")`` and ``ensure_ascii=False``. Encoding rules: Pydantic models become
    ``model_dump(mode="json")``; mappings are sorted by key (keys must be ``str``); tuples and
    lists keep their order and are equal; ``Path`` becomes ``str``; ``datetime`` and ``date``
    become ISO strings; ``bytes`` becomes ``{"__bytes__": "<hex>"}``.

    No Unicode normalisation is applied: ``"Kündigung"`` in NFC and NFD hash differently, by
    design (callers normalise first when they want equality). Types are not coerced either:
    ``stable_hash(1) != stable_hash(1.0)``, and tz-aware datetimes at different UTC offsets hash
    differently even when they denote the same instant (convert to UTC first).

    Args:
        *parts: Values built from the types above.

    Returns:
        Lower-case hex string of length 16.

    Raises:
        TypeError: A part (or nested value) has an unsupported type, or a mapping key is not str.
        ValueError: A float is NaN or infinite.
        UnicodeEncodeError: A string holds a lone surrogate (a ``ValueError`` subclass).

    Examples:
        >>> stable_hash({"b": 1, "a": "ä"})
        '921d4ad4ce4f97fb'
        >>> stable_hash("a", "b") == stable_hash("ab")
        False
    """
    payload = json.dumps(
        [_canonical(part) for part in parts],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
