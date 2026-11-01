"""Model id -> family, from the one table ``core/data/model_families.yaml`` (D74)."""

import re
import unicodedata
from functools import cache
from importlib.resources import files
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, TypeAdapter

UNKNOWN = "unknown"

_Text = Annotated[str, StringConstraints(min_length=1)]


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: _Text
    family: _Text


class _Table(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_prefixes: tuple[_Text, ...]
    patterns: tuple[_Row, ...]
    plan: dict[str, str]


@cache
def _table() -> _Table:
    text = files("pruefstand.core.data").joinpath("model_families.yaml").read_text("utf-8")
    return TypeAdapter(_Table).validate_python(yaml.safe_load(text))


@cache
def _compiled() -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(r.pattern, re.IGNORECASE), r.family) for r in _table().patterns)


def _strip_provider(model_id: str) -> str:
    lowered = model_id.lower()
    for prefix in _table().provider_prefixes:
        if lowered.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def model_family(model_id: str) -> str:
    """Infer the model family of ``model_id`` from the pattern table.

    The id is NFKC-normalised, one provider prefix (``ollama/``, ``github/``, ...) is stripped,
    then the first matching row wins (case-insensitive). The table is read once and cached.

    Args:
        model_id: A provider-qualified model id such as ``ollama/gemma3:12b``.

    Returns:
        The family name, or ``"unknown"`` when no row matches (for example embedding models).

    Examples:
        >>> model_family("ollama/gemma3:12b")
        'gemma'
        >>> model_family("github/mistral-ai/mistral-small-2503")
        'mistral'
        >>> model_family("ollama/bge-m3")
        'unknown'
    """
    rest = _strip_provider(unicodedata.normalize("NFKC", model_id))
    for pattern, family in _compiled():
        if pattern.search(rest):
            return family
    return UNKNOWN


@cache
def known_families() -> frozenset[str]:
    """Return every family name in the table (``"unknown"`` is not one of them).

    Returns:
        The frozen set of family names; the same object on every call.

    Examples:
        >>> "qwen" in known_families() and "unknown" not in known_families()
        True
    """
    return frozenset(row.family for row in _table().patterns)
