"""``safe_error``: describe an exception without any text taken from file content."""

from typing import get_args

from pydantic import BaseModel, ValidationError

from pruefstand.core.models.run import RunManifest, ScoredCase
from pruefstand.core.models.target import CaseRecord


def _known_field_names() -> frozenset[str]:
    """Names of every model field a run file can mention (never a key taken from file content)."""
    names: set[str] = set()
    todo: list[type[BaseModel]] = [RunManifest, CaseRecord, ScoredCase]
    while todo:
        model = todo.pop()
        for name, info in model.model_fields.items():
            names.add(name)
            for ann in (info.annotation, *get_args(info.annotation)):
                inner = get_args(ann) or (ann,)
                todo.extend(
                    t
                    for t in (ann, *inner)
                    if isinstance(t, type) and issubclass(t, BaseModel) and t not in todo
                )
    return frozenset(names)


_FIELDS = _known_field_names()


def safe_error(exc: BaseException) -> str:
    """Describe ``exc`` without any text taken from file content.

    Pydantic ``input`` values are dropped, and a ``loc`` part that is not a model field name
    (an extra key, a dict key) is replaced by ``<key>``; list indices are kept.
    """
    if isinstance(exc, ValidationError):
        items = exc.errors(include_url=False, include_context=False, include_input=False)
        return "; ".join(
            f"{'.'.join(_loc_part(p) for p in e['loc'])}: {e['type']}" for e in items[:5]
        )
    if isinstance(exc, UnicodeDecodeError):
        return f"invalid UTF-8 at byte {exc.start}"
    return type(exc).__name__


def _loc_part(part: object) -> str:
    if isinstance(part, int):
        return str(part)
    return part if isinstance(part, str) and part in _FIELDS else "<key>"
