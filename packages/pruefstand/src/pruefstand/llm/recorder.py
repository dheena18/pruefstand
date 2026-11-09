"""Call recorder: one row per LLM call, written to ``llm_calls.parquet`` (interfaces §3)."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from pruefstand.core.models.llm import LLMRequest, LLMResponse

SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "ts": pl.Datetime("us", "UTC"),
    "role": pl.String,
    "model": pl.String,
    "provider": pl.String,
    "prompt_id": pl.String,
    "prompt_version": pl.String,
    "prompt_tokens": pl.Int64,
    "completion_tokens": pl.Int64,
    "cost_usd": pl.Float64,
    "latency_ms": pl.Float64,
    "cached": pl.Boolean,
    "fallback": pl.Boolean,
    "error": pl.String,
}
COLUMNS: tuple[str, ...] = tuple(SCHEMA)


class CallRecorder:
    """Collects one row per call (also cache hits and failures) in memory."""

    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    @property
    def rows(self) -> tuple[dict[str, object], ...]:
        """Return the recorded rows, oldest first; each has exactly ``COLUMNS``."""
        return tuple(self._rows)

    def record(self, req: LLMRequest, resp: LLMResponse | None, error: str | None) -> None:
        """Append one row.

        Args:
            req: The request that was made.
            resp: The response, or None when the call failed.
            error: The failure text (no secrets), or None on success.
        """
        self._rows.append(
            {
                "ts": datetime.now(UTC),
                "role": req.role.value,
                "model": req.model,
                "provider": (
                    resp.provider if resp and resp.provider else req.model.split("/", 1)[0]
                ),
                "prompt_id": req.prompt_id,
                "prompt_version": req.prompt_version,
                "prompt_tokens": resp.usage.prompt_tokens if resp else 0,
                "completion_tokens": resp.usage.completion_tokens if resp else 0,
                "cost_usd": resp.cost_usd if resp else 0.0,
                "latency_ms": resp.latency_ms if resp else 0.0,
                "cached": resp.cached if resp else False,
                "fallback": resp.fallback if resp else False,
                "error": error,
            }
        )

    def to_frame(self) -> pl.DataFrame:
        """Return the rows as a frame with the explicit schema (zero rows keep their dtypes)."""
        return pl.DataFrame(
            {name: [row[name] for row in self._rows] for name in COLUMNS}, schema=SCHEMA
        )

    def to_parquet(self, path: Path) -> None:
        """Write the rows with the explicit schema (a zero-row file keeps its dtypes).

        Args:
            path: Target file; parent directories are created.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().write_parquet(path)
