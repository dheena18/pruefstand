"""RQ1 grid expander (T7.3 S1): ``grid.yaml`` -> named configs, stable hashes, RagConfig overrides.

Each config is ``rag.gpu.yaml`` plus its overrides (X3.15): :func:`apply_overrides` replaces the
``embed`` section as a whole (an embedder is one unit: model, engine, endpoint, prefixes, options)
and merges the other sections. Dense-only configs carry no compound-split axis (the analyzer only
feeds the sparse leg), so 2 embedders x (2 dense + 4 hybrid) = 12 effective configs, 18 with the
extended third embedder.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

GRID = Path(__file__).resolve().with_name("grid.yaml")


class GridConfig(BaseModel):
    """One RQ1 configuration: its name, a stable hash of the overrides, and the overrides."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    config_hash: str
    embedder: str
    retrieval: str
    chunking: str
    compound_split: bool | None
    overrides: dict[str, Any]


def overrides_hash(overrides: Mapping[str, Any]) -> str:
    """Return the first 12 hex digits of the SHA-256 of the canonical JSON of ``overrides``.

    Examples:
        >>> overrides_hash({"b": 1, "a": {"c": True}}) == overrides_hash({"a": {"c": True}, "b": 1})
        True
    """
    text = json.dumps(overrides, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _config(
    embedder: str,
    section: dict[str, Any],
    retrieval: str,
    chunk: tuple[str, Any],
    *,
    split: bool | None,
) -> GridConfig:
    overrides: dict[str, Any] = {
        "embed": section,
        "retrieval": {"hybrid": retrieval == "hybrid"},
        "chunking": chunk[1],
    }
    if split is not None:
        overrides["analyzer"] = {"compound_split": split}
    split_name = "" if split is None else ("-split" if split else "-nosplit")
    name = f"{embedder}-{retrieval}-{chunk[0]}{split_name}"
    return GridConfig(
        name=name, config_hash=overrides_hash(overrides), embedder=embedder, retrieval=retrieval,
        chunking=chunk[0], compound_split=split, overrides=overrides,
    )  # fmt: skip


def expand(grid: Mapping[str, Any] | None = None, *, extended: bool = False) -> list[GridConfig]:
    """Expand the grid into its effective configs, in a fixed order.

    Args:
        grid: the parsed ``grid.yaml`` (default: the committed file).
        extended: also expand the optional third embedder.

    Returns:
        12 configs (18 with ``extended``); hybrid configs carry ``analyzer.compound_split``.
    """
    grid = grid if grid is not None else yaml.safe_load(GRID.read_text(encoding="utf-8"))
    embedders = dict(grid["embedders"])
    if extended:
        embedders.update(grid["extended_embedders"])
    configs: list[GridConfig] = []
    for name, section in embedders.items():
        for retrieval in grid["retrieval"]:
            for chunk in grid["chunking"].items():
                splits = grid["compound_split"] if retrieval == "hybrid" else [None]
                configs.extend(_config(name, section, retrieval, chunk, split=s) for s in splits)
    return configs


def apply_overrides(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``base`` (parsed rag.gpu.yaml) with ``overrides``: ``embed`` replaced, others merged.

    Examples:
        >>> apply_overrides({"embed": {"model": "a", "options": {"num_ctx": 1}}, "top_k": 8},
        ...                 {"embed": {"model": "b"}, "retrieval": {"hybrid": False}})
        {'embed': {'model': 'b'}, 'top_k': 8, 'retrieval': {'hybrid': False}}
    """
    merged = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        if key != "embed" and isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return merged
