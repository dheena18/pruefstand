"""Review F5, D1122: the parquet reader child is bounded; the parent trusts none of its output."""

import io
import pickle
import tracemalloc
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pruefstand.ingest import records_child, records_proc
from pruefstand.ingest.records_model import OldpLimits, Problem, RowBudget
from pruefstand.ingest.records_proc import child_env, parquet_rows
from pruefstand.ingest.records_read import parquet_rows_local
from pruefstand.ingest.records_wire import encode

MIB = 1024 * 1024
BOMB_ELEMENTS = 25_000_000


def list_null_bomb(path: Path) -> Path:
    """A few hundred bytes on disk, one row whose ``list<null>`` holds 25 M elements."""
    offsets = pa.array([0, BOMB_ELEMENTS], type=pa.int32())
    tags = pa.ListArray.from_arrays(offsets, pa.nulls(BOMB_ELEMENTS))
    table = pa.table({"id": pa.array([1], pa.int64()), "content": ["Kündigung"], "tags": tags})
    pq.write_table(table, path)
    assert path.stat().st_size < 4096
    return path


def read(path: Path, limits: OldpLimits) -> tuple[list[dict[str, object]], list[Problem]]:
    problems: list[Problem] = []
    rows = [
        r for _, r in parquet_rows(path, ["id", "content", "tags"], limits, problems, RowBudget(10))
    ]
    return rows, problems


@pytest.mark.parametrize("memory", [0, 512 * MIB], ids=["in-process", "child"])
def test_a_list_null_bomb_is_a_counted_problem_not_a_row(tmp_path: Path, memory: int) -> None:
    path = list_null_bomb(tmp_path / "bomb.parquet")
    tracemalloc.start()
    try:
        rows, problems = read(path, OldpLimits(max_parquet_memory_bytes=memory))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert rows == []
    assert [p.kind for p in problems] == ["record_too_large"]
    assert f"{BOMB_ELEMENTS} list elements" in problems[0].detail
    assert peak < 64 * MIB  # the 25 M-element list was never built in this process


def test_a_small_list_stays_readable(tmp_path: Path) -> None:
    table = pa.table({"id": [1], "content": ["x"], "tags": pa.array([["a", "b"]])})
    pq.write_table(table, tmp_path / "ok.parquet")
    rows, problems = read(tmp_path / "ok.parquet", OldpLimits())
    assert rows == [{"id": 1, "content": "x", "tags": ["a", "b"]}]
    assert problems == []


def test_an_unsupported_value_type_is_a_bad_record_in_the_child(tmp_path: Path) -> None:
    table = pa.table({"id": [1, 2], "content": [b"\x00raw", None]})
    pq.write_table(table, tmp_path / "bin.parquet")
    rows, problems = read(tmp_path / "bin.parquet", OldpLimits())
    assert rows == [{"id": 2, "content": None}]
    assert [(p.kind, p.source) for p in problems] == [("bad_record", "bin.parquet:1")]


def test_an_aware_timestamp_keeps_its_wall_date(tmp_path: Path) -> None:
    stamp = datetime(2024, 3, 1, 0, 30, tzinfo=timezone(timedelta(hours=1)))
    table = pa.table({"id": [1], "content": [stamp]})
    pq.write_table(table, tmp_path / "ts.parquet")
    rows, problems = read(tmp_path / "ts.parquet", OldpLimits())
    assert problems == []
    value = rows[0]["content"]
    assert isinstance(value, datetime)
    assert value == stamp
    assert value.utcoffset() == timedelta(hours=1)
    assert value.date() == date(2024, 3, 1)  # the wall date, not the UTC date


# --- the parent side ------------------------------------------------------------------------------


def frames(*events: tuple[object, ...]) -> io.BytesIO:
    buffer = io.BytesIO()
    for event in events:
        records_child.send(buffer, event)
    buffer.seek(0)
    return buffer


def consume(
    stream: io.BytesIO, sent: int = 10
) -> tuple[list[tuple[int, dict[str, object]]], list[Problem], RowBudget]:
    problems: list[Problem] = []
    budget = RowBudget(sent)
    rows = list(records_proc.events(stream, Path("f.parquet"), OldpLimits(), problems, budget))
    return rows, problems, budget


def test_the_parent_never_unpickles_what_the_child_sends() -> None:
    raw = pickle.dumps(("row", 1, {"x": 1}))
    rows, problems, _ = consume(io.BytesIO(raw + b"\n"))
    assert rows == []
    assert [p.kind for p in problems] == ["reader_protocol"]


def test_the_parent_accepts_dates_decimals_and_fixed_offsets() -> None:
    row = {"d": date(2020, 1, 2), "t": datetime(2020, 1, 2, tzinfo=UTC), "n": Decimal("1.5")}
    rows, problems, budget = consume(frames(("row", 3, row), ("done", 9, False)))
    assert rows == [(3, row)]
    assert problems == []
    assert (budget.left, budget.hit) == (9, False)


@pytest.mark.parametrize("left", [11, -1, "9", 10])
def test_the_parent_never_takes_more_budget_than_it_sent(left: object) -> None:
    rows, problems, budget = consume(frames(("row", 1, {}), ("done", left, False)))
    assert len(rows) == 1
    assert budget.left == 9  # sent 10, received one row
    assert [p.kind for p in problems] == ["reader_protocol"]


def test_an_oversized_line_is_refused_without_reading_it_whole() -> None:
    cap = 2 * OldpLimits().max_record_bytes + MIB
    _, problems, _ = consume(io.BytesIO(b'["warning", "' + b"x" * (cap + 10) + b'"]\n'))
    assert [p.kind for p in problems] == ["reader_protocol"]
    assert "line of more than" in problems[0].detail


def test_the_parent_caps_list_items_per_row() -> None:
    line = encode(("row", 1, {"tags": [None] * 100_001}))
    _, problems, _ = consume(io.BytesIO(line))
    assert [p.kind for p in problems] == ["reader_protocol"]
    assert "list elements" in problems[0].detail


def test_the_parent_takes_no_more_rows_than_the_budget() -> None:
    rows, problems, budget = consume(frames(("row", 1, {}), ("row", 2, {})), sent=1)
    assert len(rows) == 1
    assert [p.kind for p in problems] == ["reader_protocol"]
    assert budget.left == 0


@pytest.mark.parametrize(
    "line",
    [
        b'["row", "1", {"$o": {}}]',
        b'["row", 1, {}]',
        b'["row", true, {"$o": {}}]',
        b'["row", 1, {"$o": {"x": {"$x": 1}}}]',
        b'["row", 1, {"$o": {"x": {"a": 1}}}]',
        b'["row", 1, {"$o": {"d": {"$d": "not a date"}}}]',
        b'["problem", "a", "b"]',
        b'["unknown"]',
        b'{"row": 1}',
        b'["done", 1, NaN]',
    ],
)
def test_a_malformed_event_is_a_protocol_problem(line: bytes) -> None:
    _, problems, _ = consume(io.BytesIO(line + b"\n"))
    assert [p.kind for p in problems] == ["reader_protocol"]


def test_the_child_gets_a_minimal_environment() -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "SOME_API_TOKEN": "placeholder",
        "PRUEFSTAND_GH_MODELS_TOKEN": "placeholder",
        "ARROW_IO_THREADS": "1",
        "LD_PRELOAD": "libx.so",
    }
    env = child_env(environ)
    assert set(env) == {
        "PATH",
        "HOME",
        "ARROW_IO_THREADS",
        "ARROW_DEFAULT_MEMORY_POOL",
        "MALLOC_ARENA_MAX",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
    }


def test_a_child_over_its_wall_time_is_a_read_timeout(tmp_path: Path) -> None:
    pq.write_table(pa.table({"id": [1], "content": ["x"]}), tmp_path / "a.parquet")
    rows, problems = read(tmp_path / "a.parquet", OldpLimits(max_parquet_wall_seconds=0.001))
    assert rows == []
    assert [p.kind for p in problems] == ["read_timeout"]


class FakeResource:
    RLIMIT_AS, RLIMIT_CPU, RLIM_INFINITY = 9, 0, -1

    def __init__(self) -> None:
        self.set_to: dict[int, tuple[int, int]] = {}

    def getrlimit(self, _which: int) -> tuple[int, int]:
        return (-1, -1)

    def setrlimit(self, which: int, limits: tuple[int, int]) -> None:
        self.set_to[which] = limits

    def getpagesize(self) -> int:
        return 4096


def test_the_child_pins_soft_and_hard_limits_and_caps_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeResource()
    monkeypatch.setattr(records_child, "resource", fake)
    monkeypatch.setattr(records_child, "_virtual_bytes", lambda: 1000 * MIB)
    limits = OldpLimits(max_parquet_memory_bytes=512 * MIB, max_parquet_cpu_seconds=60)
    assert records_child.limit_resources(limits) is None
    assert fake.set_to[fake.RLIMIT_AS] == (1512 * MIB, 1512 * MIB)
    assert fake.set_to[fake.RLIMIT_CPU] == (60, 60)


def test_in_process_reading_still_checks_the_list_size(tmp_path: Path) -> None:
    path = list_null_bomb(tmp_path / "b.parquet")
    problems: list[Problem] = []
    limits = OldpLimits(max_parquet_memory_bytes=0)
    rows = list(parquet_rows_local(path, ["id", "tags"], limits, problems, RowBudget(5)))
    assert rows == []
    assert problems[0].kind == "record_too_large"
