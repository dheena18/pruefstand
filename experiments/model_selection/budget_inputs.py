"""Measured inputs of the T3.1b budgets: generator output cap and the reranker lane (T3.1b S5).

* the generator's output tokens are capped by ``generation.max_tokens`` of the tier-2 profile
  ``apps/rag-demo/configs/rag.gpu.yaml`` (not the phase-1 constant 200);
* the reranker lane uses the measured seconds per query from ``results/rerank_latency.csv``
  (``rerank_bench.py``, VM CPU); without a measurement it falls back to the phase-1 assumption
  (1.2 s) and says so (``source`` = ``assumed``).
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]
GPU_CONFIG = ROOT / "apps/rag-demo/configs/rag.gpu.yaml"
RERANK_CSV = Path(__file__).resolve().parent / "results" / "rerank_latency.csv"
ASSUMED_RERANK_S = 1.2


def generator_out_tokens(path: Path = GPU_CONFIG) -> int:
    """``generation.max_tokens`` of the tier-2 profile (else its top-level ``max_tokens``).

    Raises:
        ValueError: neither is a positive integer.
    """
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    value = (cfg.get("generation") or {}).get("max_tokens", cfg.get("max_tokens"))
    if not isinstance(value, int) or value <= 0:
        msg = f"{path}: no positive generation.max_tokens"
        raise ValueError(msg)
    return value


@dataclass(frozen=True)
class RerankInput:
    """Reranker seconds per query (wall time / queries at ``concurrency``) and their source."""

    seconds_per_query: float
    concurrency: int
    source: Literal["measured", "assumed"]


def rerank_input(path: Path = RERANK_CSV, concurrency: int = 1) -> RerankInput:
    """The latest measured ``wall_per_query_s`` at ``concurrency``, else the 1.2 s assumption.

    ``wall_per_query_s`` already includes the concurrency (wall time / queries), so the lane is
    ``queries x seconds_per_query`` (``budget.rerank_verdict(..., concurrency=1)``).
    """
    rows: list[dict[str, str]] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = [r for r in csv.DictReader(handle) if int(r["concurrency"]) == concurrency]
    if not rows:
        return RerankInput(ASSUMED_RERANK_S, concurrency, "assumed")
    latest = max(rows, key=lambda r: r["date"])
    return RerankInput(float(latest["wall_per_query_s"]), concurrency, "measured")
