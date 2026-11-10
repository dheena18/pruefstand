r"""Wire format between the parquet reader process and its parent (review F5, D1122).

One JSON object per line, no pickle: ``["row", number, row]``, ``["problem", source, kind,
detail]``, ``["warning", text]``, ``["memory", text]``, ``["done", rows_left, hit]``. JSON has
no dates, so the few non-JSON values the OLDP rows carry are tagged one-key objects: ``{"$d":
iso}`` (date), ``{"$dt": iso}`` (datetime, with its offset), ``{"$t": iso}`` (time), ``{"$td":
[days, seconds, microseconds]}``, ``{"$n": text}`` (Decimal), ``{"$f": "nan" | "inf" | "-inf"}``,
and a real mapping (also the row itself) is ``{"$o": {...}}``. The parent decodes with strict
caps: line length, text length, list items per row, nesting depth; anything else is a protocol
error.

Examples:
    >>> from datetime import date
    >>> line = encode(("row", 3, {"date": date(2024, 3, 1), "court": {"name": "BGH"}}))
    >>> line
    b'["row", 3, {"$o": {"date": {"$d": "2024-03-01"}, "court": {"$o": {"name": "BGH"}}}}]\n'
    >>> decode(line, max_text=100, max_items=10)
    ('row', 3, {'date': datetime.date(2024, 3, 1), 'court': {'name': 'BGH'}})
"""

import json
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from pruefstand.core.errors import PruefstandError

MAX_DEPTH = 8
_FLOATS = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}


class WireError(PruefstandError):
    """A line that is not one of the exact events, or a value above a cap."""


def _encode_value(value: object) -> object:  # noqa: PLR0911 (one return per wire type)
    if isinstance(value, float) and not math.isfinite(value):
        return {"$f": "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")}
    if value is None or isinstance(value, str | int | float):
        return value
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, time):
        return {"$t": value.isoformat()}
    if isinstance(value, timedelta):
        return {"$td": [value.days, value.seconds, value.microseconds]}
    if isinstance(value, Decimal):
        return {"$n": str(value)}
    if isinstance(value, list | tuple):
        return [_encode_value(v) for v in value]
    if isinstance(value, dict):
        return {"$o": {str(k): _encode_value(v) for k, v in value.items()}}
    msg = f"unsupported value type {type(value).__name__}"
    raise WireError(msg)


def encode(event: tuple[object, ...]) -> bytes:
    """One event as a JSON line (``WireError`` for a value the wire cannot carry)."""
    data = [_encode_value(v) for v in event]
    return (json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


class _Caps:
    def __init__(self, max_text: int, max_items: int) -> None:
        self.max_text, self.max_items, self.items = max_text, max_items, 0


def _tagged(tag: str, raw: object, caps: _Caps, depth: int) -> object:  # noqa: PLR0911
    if tag == "$o" and isinstance(raw, dict):
        return {k: _decode_value(v, caps, depth + 1) for k, v in raw.items()}
    if tag == "$f" and isinstance(raw, str) and raw in _FLOATS:
        return _FLOATS[raw]
    if not isinstance(raw, str | list) or len(raw) > 64:
        msg = f"invalid {tag} value"
        raise WireError(msg)
    try:
        if tag == "$dt" and isinstance(raw, str):
            return datetime.fromisoformat(raw)
        if tag == "$d" and isinstance(raw, str):
            return date.fromisoformat(raw)
        if tag == "$t" and isinstance(raw, str):
            return time.fromisoformat(raw)
        if tag == "$n" and isinstance(raw, str):
            return Decimal(raw)
        if tag == "$td" and isinstance(raw, list) and all(type(v) is int for v in raw):
            return timedelta(*raw[:3])
    except (ValueError, OverflowError, InvalidOperation, TypeError):
        pass
    msg = f"invalid {tag} value"
    raise WireError(msg)


def _decode_value(value: object, caps: _Caps, depth: int) -> object:
    if depth > MAX_DEPTH:
        msg = f"a value nested deeper than {MAX_DEPTH} levels"
        raise WireError(msg)
    if isinstance(value, str) and len(value) > caps.max_text:
        msg = f"a text of {len(value)} characters > {caps.max_text}"
        raise WireError(msg)
    if value is None or isinstance(value, str | int | float):
        return value
    if isinstance(value, list):
        caps.items += len(value)
        if caps.items > caps.max_items:
            msg = f"more than {caps.max_items} list elements in one row"
            raise WireError(msg)
        return [_decode_value(v, caps, depth + 1) for v in value]
    if isinstance(value, dict) and len(value) == 1:
        ((tag, raw),) = value.items()
        return _tagged(str(tag), raw, caps, depth)
    msg = "an untagged object"
    raise WireError(msg)


_SHAPES: dict[str, tuple[type, ...]] = {
    "row": (int, dict),
    "problem": (str, str, str),
    "warning": (str,),
    "memory": (str,),
    "done": (int, bool),
}


def decode(line: bytes, *, max_text: int, max_items: int) -> tuple[object, ...]:
    """Decode and check one event line.

    Raises:
        WireError: Not JSON, not an exact event, or a value above a cap.
    """
    try:
        data = json.loads(line, parse_constant=_no_constant)
    except (ValueError, RecursionError) as error:
        msg = f"the reader sent a line that is not JSON ({type(error).__name__})"
        raise WireError(msg) from None
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        msg = "the reader sent an event that is not a tagged list"
        raise WireError(msg)
    tag, args = data[0], data[1:]
    shape = _SHAPES.get(tag)
    if shape is None or len(args) != len(shape):
        msg = f"the reader sent a malformed {tag[:20]!r} event"
        raise WireError(msg)
    if tag == "row":
        if not isinstance(args[1], dict) or set(args[1]) != {"$o"}:
            msg = "the reader sent a row that is not a tagged mapping"
            raise WireError(msg)
        args = [args[0], _decode_value(args[1], _Caps(max_text, max_items), 0)]
    if not all(_is(v, t) for v, t in zip(args, shape, strict=True)):
        msg = f"the reader sent a malformed {tag[:20]!r} event"
        raise WireError(msg)
    return (tag, *args)


def _is(value: object, kind: type) -> bool:
    """``isinstance`` where a bool is not an int."""
    return isinstance(value, kind) and (kind is bool or not isinstance(value, bool))


def _no_constant(name: str) -> object:
    msg = f"JSON constant {name}"
    raise ValueError(msg)
