"""processed.jsonl and nightly_counter (D102, D288, D299, P4.4)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from gate_orchestrator.models import ProcessedEntry
from gate_orchestrator.state import (
    append_processed,
    finish_nightly,
    increment_counter,
    load_processed,
    nightly_counter_path,
    read_counter,
)

AT = datetime(2026, 11, 10, 7, 30, tzinfo=UTC)


def _entry(
    pr: int = 7, result: str = "pass", run_id: str = "run-1", dispatch: int = 11
) -> ProcessedEntry:
    return ProcessedEntry(
        pr=pr, head_sha="1" * 40, dispatch_run_id=dispatch, result=result, run_id=run_id, at=AT
    )


def test_round_trip_keeps_every_field(tmp_path: Path) -> None:
    path = tmp_path / "state" / "processed.jsonl"
    append_processed(path, _entry())
    append_processed(path, _entry(pr=8, result="error", run_id="run-2", dispatch=12))
    loaded = load_processed(path)
    assert loaded == [_entry(), _entry(pr=8, result="error", run_id="run-2", dispatch=12)]
    assert loaded[0].at == AT
    assert loaded[0].dispatch_run_id == 11


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_processed(tmp_path / "nope.jsonl") == []


def test_corrupt_line_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "processed.jsonl"
    append_processed(path, _entry())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"pr": "sieben"}\n')
    with pytest.raises(ValueError, match=r"processed\.jsonl:2: corrupt"):
        load_processed(path)


def test_duplicates_collapse_to_the_last_line(tmp_path: Path) -> None:
    path = tmp_path / "processed.jsonl"
    append_processed(path, _entry(result="error"))
    append_processed(path, _entry(result="pass"))
    append_processed(path, _entry(dispatch=12))
    loaded = load_processed(path)
    assert [(e.dispatch_run_id, e.result) for e in loaded] == [(11, "pass"), (12, "pass")]


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        ProcessedEntry(
            pr=1,
            head_sha="1" * 40,
            dispatch_run_id=1,
            result="pass",
            run_id="r",
            at=datetime(2026, 1, 1),  # noqa: DTZ001 - the naive input under test
        )


def test_counter_path_from_env() -> None:
    assert nightly_counter_path({"PRUEFSTAND_NIGHTLY_COUNTER": "/x/c"}) == Path("/x/c")
    home = {"PRUEFSTAND_HOME": "/srv/ph"}
    assert nightly_counter_path(home) == Path("/srv/ph/state/nightly_counter")
    with pytest.raises(ValueError, match="unset"):
        nightly_counter_path({})


def test_counter_missing_is_zero_and_increment_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "state" / "nightly_counter"
    assert read_counter(path) == 0
    path.parent.mkdir()
    path.write_text("4\n", encoding="utf-8")
    assert increment_counter(path) == 5
    assert path.read_text(encoding="utf-8") == "5\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["nightly_counter"]


@pytest.mark.parametrize("text", ["", "-1", "drei", "1.5"])
def test_invalid_counter_is_an_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "nightly_counter"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="nightly counter"):
        read_counter(path)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", 5),
        ("failed", 5),
        ("aborted: window_exceeded", 4),
        ("skipped: maintenance", 4),
        ("skipped: runner busy", 4),
        ("skipped: preflight tunnel", 4),
    ],
)
def test_counter_moves_only_after_a_completed_nightly(
    tmp_path: Path, status: str, expected: int
) -> None:
    path = tmp_path / "nightly_counter"
    path.write_text("4", encoding="utf-8")
    assert finish_nightly(path, status) == expected
    assert read_counter(path) == expected
