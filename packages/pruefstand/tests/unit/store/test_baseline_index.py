"""``index.json``: the only file the git branch holds (T6.1 S4, X2.7)."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pruefstand.core.errors import StoreError
from pruefstand.store.baseline_index import (
    MAX_INDEX_BYTES,
    BaselineIndex,
    IndexEntry,
    parse_index,
    reconcile_index,
    render_index,
    with_promotion,
)

FP = "0123456789abcdef"
NOW = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def entry(n: int, **changes: Any) -> IndexEntry:
    data: dict[str, Any] = {
        "run_id": f"20261102T2200{n:02d}-{n:06x}",
        "manifest_sha256": f"{n:064x}",
        "promoted_at": NOW,
        "git_sha": None,
    }
    return IndexEntry.model_validate({**data, **changes})


def test_an_empty_index_renders_and_parses() -> None:
    empty = BaselineIndex.empty()
    assert parse_index(render_index(empty)) == empty


def test_a_promotion_appends_the_newest_last_and_round_trips() -> None:
    index = with_promotion(
        with_promotion(BaselineIndex.empty(), FP, "main", entry(1)), FP, "main", entry(2)
    )
    runs = index.entries[FP]["main"].runs
    assert [r.run_id for r in runs] == [entry(1).run_id, entry(2).run_id]
    assert parse_index(render_index(index)) == index


def test_promoting_the_same_run_again_replaces_its_entry() -> None:
    first = with_promotion(BaselineIndex.empty(), FP, "main", entry(1))
    again = with_promotion(first, FP, "main", entry(1, manifest_sha256="f" * 64))
    runs = again.entries[FP]["main"].runs
    assert len(runs) == 1
    assert runs[0].manifest_sha256 == "f" * 64


def test_the_rendering_is_stable_and_sorted() -> None:
    index = with_promotion(BaselineIndex.empty(), "b" * 16, "main", entry(1))
    index = with_promotion(index, "a" * 16, "main", entry(2))
    text = render_index(index).decode("utf-8")
    assert text.endswith("\n")
    assert text.index("a" * 16) < text.index("b" * 16)
    assert render_index(parse_index(text.encode())) == text.encode()


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "a" * 65, "x y"])
def test_a_hostile_fingerprint_key_is_refused(bad: str) -> None:
    doc = {"schema_version": "1", "entries": {bad: {"main": {"runs": []}}}}
    with pytest.raises(StoreError, match="fingerprint"):
        parse_index(json.dumps(doc).encode())


@pytest.mark.parametrize("bad", ["release", "nightly-b3", "../main", ""])
def test_a_hostile_ref_key_is_refused(bad: str) -> None:
    doc = {"schema_version": "1", "entries": {FP: {bad: {"runs": []}}}}
    with pytest.raises(StoreError, match="ref"):
        parse_index(json.dumps(doc).encode())


def test_a_hostile_run_id_is_refused() -> None:
    row = {
        "run_id": "../../x",
        "manifest_sha256": "0" * 64,
        "promoted_at": NOW.isoformat(),
        "git_sha": None,
    }
    doc = {"schema_version": "1", "entries": {FP: {"main": {"runs": [row]}}}}
    with pytest.raises(StoreError, match="run id"):
        parse_index(json.dumps(doc).encode())


@pytest.mark.parametrize(
    "payload", [b"", b"[]", b"{", b"null", b'{"schema_version": "2", "entries": {}}']
)
def test_garbage_is_a_store_error(payload: bytes) -> None:
    with pytest.raises(StoreError):
        parse_index(payload)


def test_an_unknown_field_is_refused_without_echoing_it() -> None:
    doc = {"schema_version": "1", "entries": {}, "secret-looking-key": 1}
    with pytest.raises(StoreError) as excinfo:
        parse_index(json.dumps(doc).encode())
    assert "secret-looking-key" not in str(excinfo.value)


def test_an_oversized_index_is_refused_before_parsing() -> None:
    with pytest.raises(StoreError, match="larger than"):
        parse_index(b" " * (MAX_INDEX_BYTES + 1))


def test_parsing_is_linear_in_the_number_of_entries() -> None:
    def build(count: int) -> bytes:
        index = BaselineIndex.empty()
        for n in range(count):
            index = with_promotion(
                index, f"{n:016x}", "main", entry(n % 60, run_id=f"20261102T000000-{n:06x}")
            )
        return render_index(index)

    small, big = build(100), build(1000)
    best_small = best_big = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        parse_index(small)
        best_small = min(best_small, time.perf_counter() - t0)
        t0 = time.perf_counter()
        parse_index(big)
        best_big = min(best_big, time.perf_counter() - t0)
    assert best_big / best_small < 10 * 4  # 10x the entries; a quadratic parser would be ~100x


def test_reconcile_drops_what_the_disk_no_longer_has(tmp_path: Path) -> None:
    gone, kept, current = entry(1), entry(2), entry(3)
    index = BaselineIndex.empty()
    for item in (gone, kept, current):
        index = with_promotion(index, FP, "main", item)
    index = with_promotion(index, "a" * 16, "main", entry(4))
    (tmp_path / FP / "main").mkdir(parents=True)
    (tmp_path / FP / "history" / kept.run_id).mkdir(parents=True)
    reconciled = reconcile_index(index, tmp_path)
    assert [r.run_id for r in reconciled.entries[FP]["main"].runs] == [kept.run_id, current.run_id]
    assert "a" * 16 not in reconciled.entries


def test_reconcile_keeps_the_current_entry_even_without_a_history_directory(tmp_path: Path) -> None:
    current = entry(2)
    index = with_promotion(BaselineIndex.empty(), FP, "main", current)
    (tmp_path / FP / "main").mkdir(parents=True)
    assert reconcile_index(index, tmp_path).entries[FP]["main"].runs[-1].run_id == current.run_id


def test_reconcile_drops_a_ref_whose_directory_is_gone(tmp_path: Path) -> None:
    index = with_promotion(BaselineIndex.empty(), FP, "main", entry(1))
    (tmp_path / FP).mkdir()
    assert reconcile_index(index, tmp_path).entries == {}
