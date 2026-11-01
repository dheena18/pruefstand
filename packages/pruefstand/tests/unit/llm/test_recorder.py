from pathlib import Path

import polars as pl

from pruefstand.core.models.llm import LLMRequest, LLMResponse, LLMRole, Message
from pruefstand.core.models.target import Usage
from pruefstand.llm.recorder import COLUMNS, CallRecorder

EXPECTED = [
    "ts", "role", "model", "provider", "prompt_id", "prompt_version", "prompt_tokens",
    "completion_tokens", "cost_usd", "latency_ms", "cached", "fallback", "error",
]  # fmt: skip


def _req(i: int = 0) -> LLMRequest:
    return LLMRequest(
        role=LLMRole.DATAGEN,
        model="github/openai/gpt-4o-mini",
        messages=(Message(role="user", content=f"Frage {i}"),),
        prompt_id="echo",
        prompt_version="v1",
    )


def _resp() -> LLMResponse:
    return LLMResponse(
        text="ok",
        model="github/openai/gpt-4o-mini",
        usage=Usage(prompt_tokens=7, completion_tokens=3),
        cost_usd=0.0,
        latency_ms=42.5,
        cached=False,
        provider="github",
    )


def _check_dtypes(df: pl.DataFrame) -> None:
    assert df.columns == EXPECTED
    assert df.schema["ts"] == pl.Datetime("us", "UTC")
    for name in ("role", "model", "provider", "prompt_id", "prompt_version", "error"):
        assert df.schema[name] == pl.String
    assert df.schema["prompt_tokens"] == pl.Int64
    assert df.schema["completion_tokens"] == pl.Int64
    assert df.schema["cost_usd"] == pl.Float64
    assert df.schema["latency_ms"] == pl.Float64
    assert df.schema["cached"] == pl.Boolean
    assert df.schema["fallback"] == pl.Boolean


def test_columns_constant_matches_interface() -> None:
    assert list(COLUMNS) == EXPECTED


def test_three_records_round_trip_through_parquet(tmp_path: Path) -> None:
    rec = CallRecorder()
    rec.record(_req(0), _resp(), None)
    rec.record(_req(1), _resp(), None)
    rec.record(_req(2), None, "LLMError: HTTP 503")
    out = tmp_path / "llm_calls.parquet"
    rec.to_parquet(out)
    df = pl.read_parquet(out)
    _check_dtypes(df)
    assert df.height == 3
    assert df["prompt_tokens"].to_list() == [7, 7, 0]
    assert df["error"].to_list() == [None, None, "LLMError: HTTP 503"]
    assert df["provider"].to_list() == ["github"] * 3
    assert df["role"][0] == "datagen"


def test_zero_records_keep_documented_dtypes(tmp_path: Path) -> None:
    out = tmp_path / "empty.parquet"
    CallRecorder().to_parquet(out)
    df = pl.read_parquet(out)
    _check_dtypes(df)
    assert df.height == 0
    assert pl.Null not in df.dtypes


def test_rows_have_exactly_the_thirteen_columns() -> None:
    rec = CallRecorder()
    rec.record(_req(), _resp(), None)
    assert list(rec.rows[0]) == EXPECTED
