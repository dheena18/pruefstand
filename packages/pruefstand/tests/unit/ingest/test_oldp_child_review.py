"""Opus review of the F5 fix (D1122): pre-parse caps, keys, list views, timeouts, fail closed."""

import io
import json
import signal
import tracemalloc
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pruefstand.ingest import records_child, records_proc
from pruefstand.ingest.records_clean import RowRejectedError, clean_row
from pruefstand.ingest.records_model import OldpLimits, Problem, RowBudget
from pruefstand.ingest.records_proc import Watch, events, parquet_rows
from pruefstand.ingest.records_read import list_elements, parquet_rows_local
from pruefstand.ingest.records_wire import encode

MIB = 1024 * 1024
MANY = 25_000_000


def consume(line: bytes, limits: OldpLimits | None = None) -> tuple[int, list[Problem], int]:
    """Rows and problems of one line; the traced Python allocation peak while reading it."""
    problems: list[Problem] = []
    stream = io.BytesIO(line)
    tracemalloc.start()
    try:
        rows = list(
            events(stream, Path("f.parquet"), limits or OldpLimits(), problems, RowBudget(5))
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return len(rows), problems, peak


@pytest.mark.parametrize("item", [b"[]", b"{}", b"0", b'""'])
def test_a_line_of_many_tiny_values_is_refused_before_parsing(item: bytes) -> None:
    line = b'["warning", [' + b",".join([item] * 6_000_000) + b"]]\n"  # ~20 MB, under the cap
    rows, problems, peak = consume(line)
    del line
    assert rows == 0
    assert [p.kind for p in problems] == ["reader_protocol"]
    assert "JSON " in problems[0].detail
    assert peak < 16 * MIB  # json.loads would build 1 M objects (tens of MiB)


def test_commas_inside_texts_do_not_count() -> None:
    text = "§ 1, Abs. 2, Satz 3, " * 50_000  # 150 000 commas inside one string
    rows, problems, _ = consume(encode(("row", 1, {"content": text})))
    assert (rows, problems) == (1, [])


def test_mapping_keys_count_against_the_cap_in_the_parent() -> None:
    row = {"court": {f"k{n}": n for n in range(20)}}
    rows, problems, _ = consume(encode(("row", 1, row)), OldpLimits(max_list_elements=10))
    assert rows == 0
    assert "mapping keys" in problems[0].detail


def test_mapping_keys_count_against_the_cap_in_the_child() -> None:
    with pytest.raises(RowRejectedError, match="mapping keys"):
        clean_row({"court": {f"k{n}": n for n in range(20)}}, OldpLimits(max_list_elements=10))


@pytest.mark.parametrize("large", [False, True])
def test_list_views_are_counted(*, large: bool) -> None:
    kind = pa.LargeListViewArray if large else pa.ListViewArray
    width = pa.int64() if large else pa.int32()
    array = kind.from_arrays(pa.array([0], width), pa.array([MANY], width), pa.nulls(MANY))
    assert list_elements(array) == MANY


def test_a_list_view_bomb_in_a_file_is_refused_in_process(tmp_path: Path) -> None:
    tags = pa.ListViewArray.from_arrays(
        pa.array([0], pa.int32()), pa.array([MANY], pa.int32()), pa.nulls(MANY)
    )
    pq.write_table(pa.table({"id": [1], "tags": tags}), tmp_path / "v.parquet")
    problems: list[Problem] = []
    limits = OldpLimits(max_parquet_memory_bytes=0)
    rows = list(
        parquet_rows_local(tmp_path / "v.parquet", ["id", "tags"], limits, problems, RowBudget(5))
    )
    assert rows == []
    assert [p.kind for p in problems] == ["record_too_large"]


def test_in_process_reading_cleans_rows_too(tmp_path: Path) -> None:
    pq.write_table(pa.table({"id": [1, 2], "content": [b"raw", None]}), tmp_path / "b.parquet")
    problems: list[Problem] = []
    limits = OldpLimits(max_parquet_memory_bytes=0)
    rows = list(
        parquet_rows_local(
            tmp_path / "b.parquet", ["id", "content"], limits, problems, RowBudget(5)
        )
    )
    assert rows == [(2, {"id": 2, "content": None})]
    assert [p.kind for p in problems] == ["bad_record"]


class FakeChild:
    def __init__(self, code: int) -> None:
        self.stdout = io.BytesIO(b"")
        self.code = code

    def wait(self) -> int:
        return self.code


@pytest.mark.parametrize(
    ("code", "kind"),
    [(-signal.SIGXCPU, "read_timeout"), (-signal.SIGKILL, "memory_limit"), (1, "memory_limit")],
)
def test_how_a_dead_reader_is_reported(code: int, kind: str) -> None:
    problems: list[Problem] = []
    child = FakeChild(code)
    rows = records_proc._child_rows(
        child,  # type: ignore[arg-type]  # a stand-in with stdout and wait
        Path("f.parquet"),
        OldpLimits(),
        problems,
        RowBudget(5),
        watch=Watch(10),
    )
    assert list(rows) == []
    assert [p.kind for p in problems] == [kind]


def test_a_real_cpu_timeout_is_a_read_timeout(tmp_path: Path) -> None:
    pq.write_table(pa.table({"id": [1], "content": ["x"]}), tmp_path / "a.parquet")
    problems: list[Problem] = []
    limits = OldpLimits(max_parquet_cpu_seconds=0)  # soft 0 s: SIGXCPU at the first tick
    rows = list(
        parquet_rows(tmp_path / "a.parquet", ["id", "content"], limits, problems, RowBudget(5))
    )
    assert rows == []
    assert [p.kind for p in problems] == ["read_timeout"]
    assert "CPU time" in problems[0].detail


def test_the_watch_counts_only_the_time_spent_waiting() -> None:
    now = [0.0]
    watch = Watch(10.0, clock=lambda: now[0])
    assert watch.left() is None  # nothing to wait for yet
    watch.waiting()
    now[0] = 4.0
    watch.consumed()
    now[0] = 1000.0  # the caller took long over its row: not charged
    assert watch.left() is None
    watch.waiting()
    now[0] = 1005.0
    assert watch.left() == pytest.approx(1.0)
    now[0] = 1007.0
    assert watch.left() == pytest.approx(-1.0)


def test_limits_that_cannot_be_set_stop_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(records_child, "limit_resources", lambda _limits: "no /proc")
    out = io.BytesIO()
    spec = '{"path": "nowhere.parquet", "columns": ["id"], "limits": {}, "left": 5}'
    assert records_child.run([spec], out) == 0
    assert out.getvalue().startswith(b'["memory", "limits not set, file not read')


def test_the_opt_in_reads_without_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pq.write_table(pa.table({"id": [1]}), tmp_path / "a.parquet")
    monkeypatch.setattr(records_child, "limit_resources", lambda _limits: "no /proc")
    out = io.BytesIO()
    path = str(tmp_path / "a.parquet")
    limits = {"allow_unlimited_reader": True}
    spec = json.dumps({"path": path, "columns": ["id"], "limits": limits, "left": 5})
    records_child.run([spec], out)
    assert b'["warning", "no /proc"]' in out.getvalue()
    assert b'["row", 1,' in out.getvalue()
