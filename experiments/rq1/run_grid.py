"""RQ1 grid runs (T7.3 S2), offline part: the materialised, validated config of every grid cell.

D1272: the ``bge_m3`` arm is **derived from main's** ``rag.gpu.yaml`` at run time (its ``embed``
section, which reaches bge-m3 through ``LLM_PROXY_URL`` with the candidate key, D1081), so RQ1
candidates take the gated candidates' sandboxed path and never the Ollama tunnel; the committed
``bge_m3`` entry of ``grid.yaml`` is only an expander placeholder. The grid hashes cover the
derived section. Every cell is ``rag.gpu.yaml`` plus its overrides (``grid.apply_overrides``),
parsed with rag-demo's own ``parse_config`` against the model catalogue, and stored under
``runs/rq1/<rag config_hash>/rag.yaml``; ``runs/rq1/grid.json`` lists the cells.

Usage::

    uv run python experiments/rq1/run_grid.py --seed 1234 [--extended] [--out runs/rq1]

The index builds and the ``rq1`` runs (``/v1/retrieve`` for every case, ``/v1/query`` for the
correctness subsample, ``plan.py``) go through the tier-2 stack runner of T6.2b; this script
fixes and checks what each cell is.
"""

import argparse
import copy
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

# run as a script: import rq1.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rq1.grid import GRID, GridConfig, apply_overrides, expand

from pruefstand.core.errors import ConfigError
from rag_demo.config import config_hash, parse_config

REPO = Path(__file__).resolve().parents[2]
GPU_CONFIG = REPO / "apps/rag-demo/configs/rag.gpu.yaml"
CATALOGUE = REPO / "infra/gpu/models.yaml"
DERIVED = "bge_m3"  # the arm whose embed section comes from rag.gpu.yaml (D1272)
# the only endpoint variables a cell may name: llm-proxy (bge-m3, D1272), VM CPU TEI (e5, D1263)
ALLOWED_ENDPOINT_ENVS = frozenset({"LLM_PROXY_URL", "EMBED_URL"})


def load_yaml(path: Path) -> dict[str, Any]:
    """A YAML mapping from ``path``.

    Raises:
        ConfigError: the file is not a YAML mapping.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: not a YAML mapping"
        raise ConfigError(msg)
    return data


def derived_grid(grid: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    """``grid`` with the ``bge_m3`` arm replaced by ``base``'s ``embed`` section (D1272)."""
    out = copy.deepcopy(dict(grid))
    out["embedders"] = {**out["embedders"], DERIVED: copy.deepcopy(dict(base["embed"]))}
    return out


class Cell:
    """One grid cell: its grid config, the full rag-demo config and that config's hash."""

    def __init__(self, grid: GridConfig, config: dict[str, Any], rag_hash: str) -> None:
        """Hold the parts (built by :func:`materialise`)."""
        self.grid = grid
        self.config = config
        self.rag_hash = rag_hash


def materialise(
    base: Mapping[str, Any], grid: Mapping[str, Any], *, extended: bool = False
) -> list[Cell]:
    """Every cell as a full, validated rag-demo config, in the expander's order.

    Raises:
        ConfigError: a cell's embed endpoint variable is not in ``ALLOWED_ENDPOINT_ENVS``,
            or two cells have the same rag-demo config hash.
        pydantic.ValidationError: a cell is not a valid ``rag.gpu.yaml`` (rag-demo's own
            ``ConfigError`` for a catalogue mismatch).
    """
    cells = []
    for cfg in expand(derived_grid(grid, base), extended=extended):
        config = apply_overrides(base, cfg.overrides)
        endpoint = config["embed"].get("endpoint_env")
        if endpoint not in ALLOWED_ENDPOINT_ENVS:
            msg = (
                f"{cfg.name}: embed endpoint {endpoint} is not one of "
                f"{sorted(ALLOWED_ENDPOINT_ENVS)} (it would bypass llm-proxy, D1272)"
            )
            raise ConfigError(msg)
        parsed = parse_config(yaml.safe_dump(config, sort_keys=False), CATALOGUE)
        cells.append(Cell(cfg, config, config_hash(parsed)))
    hashes = [c.rag_hash for c in cells]
    if len(set(hashes)) != len(hashes):
        msg = "two grid cells have the same rag-demo config hash"
        raise ConfigError(msg)
    return cells


def write_plan(out: Path, cells: Sequence[Cell], seed: int) -> Path:
    """Write ``<out>/<rag_hash>/rag.yaml`` per cell and ``<out>/grid.json``; return the manifest."""
    rows = []
    for cell in cells:
        folder = out / cell.rag_hash
        folder.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(cell.config, sort_keys=False, allow_unicode=True)
        (folder / "rag.yaml").write_text(text, encoding="utf-8")
        rows.append({
            "name": cell.grid.name, "rag_config_hash": cell.rag_hash,
            "grid_hash": cell.grid.config_hash, "embedder": cell.grid.embedder,
            "embed_endpoint_env": cell.config["embed"].get("endpoint_env"),
            "retrieval": cell.grid.retrieval, "chunking": cell.grid.chunking,
            "compound_split": cell.grid.compound_split,
        })  # fmt: skip
    manifest = out / "grid.json"
    body = {"seed": seed, "derived_from": "apps/rag-demo/configs/rag.gpu.yaml", "cells": rows}
    manifest.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Materialise, check and write the grid; print one line per cell."""
    parser = argparse.ArgumentParser(description="RQ1 grid cells (T7.3 S2, offline part)")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("runs/rq1"))
    args = parser.parse_args(argv)
    cells = materialise(load_yaml(GPU_CONFIG), load_yaml(GRID), extended=args.extended)
    manifest = write_plan(args.out, cells, args.seed)
    for cell in cells:
        print(f"{cell.rag_hash}  {cell.grid.name}")
    print(f"{manifest}: {len(cells)} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
