"""Row values the parquet readers may hand on (review F5, D1122), in the child and in process.

Only ``str``/``int``/``float``/``bool``/``None``, dates, times, ``timedelta``, ``Decimal`` and
dicts/lists of them; texts up to ``max_record_bytes`` characters; at most ``max_list_elements``
list items **and mapping keys** together per row; depth 8. An aware datetime keeps its fixed
offset, an aware time drops its zone.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from pruefstand.core.errors import PruefstandError
from pruefstand.ingest.records_model import OldpLimits

_MAX_DEPTH = 8
_SCALARS = (str, int, float, bool, type(None), Decimal, date, time, timedelta)


class RowRejectedError(PruefstandError):
    """A row value no reader may hand on."""


def _count(items: list[int], add: int, limits: OldpLimits) -> None:
    items[0] += add
    if items[0] > limits.max_list_elements:
        msg = f"more than {limits.max_list_elements} list elements or mapping keys"
        raise RowRejectedError(msg)


def _clean(value: object, limits: OldpLimits, depth: int, items: list[int]) -> object:
    if depth > _MAX_DEPTH:
        msg = f"nested deeper than {_MAX_DEPTH} levels"
        raise RowRejectedError(msg)
    if isinstance(value, str) and len(value) > limits.max_record_bytes:
        msg = f"a text of {len(value)} characters"
        raise RowRejectedError(msg)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=timezone(value.utcoffset() or timedelta(0)))
    if isinstance(value, time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if isinstance(value, _SCALARS):
        return value
    if isinstance(value, list | tuple):
        _count(items, len(value), limits)
        return [_clean(v, limits, depth + 1, items) for v in value]
    if isinstance(value, dict):
        _count(items, len(value), limits)
        return {str(k): _clean(v, limits, depth + 1, items) for k, v in value.items()}
    msg = f"unsupported value type {type(value).__name__}"
    raise RowRejectedError(msg)


def clean_row(row: dict[str, object], limits: OldpLimits) -> dict[str, object]:
    """The row as a reader may hand it on.

    Raises:
        RowRejectedError: A value of another type, too long, too deep, or too many list
            elements and mapping keys.
    """
    items = [0]
    _count(items, len(row), limits)
    return {str(k): _clean(v, limits, 1, items) for k, v in row.items()}
