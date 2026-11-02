"""``prune_baselines``: last N per fingerprint, unused fingerprints, release anchors kept (D110)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from testsupport.store_support import FP, run_id, run_of

from pruefstand.core.errors import StoreError
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.retention import prune_baselines

NOW = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def clock_at(start: datetime) -> Callable[[], datetime]:
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return start + timedelta(seconds=state["n"])

    return tick


def fill(
    root: Path, count: int, *, fp: str = FP, start: datetime = NOW - timedelta(days=1)
) -> None:
    store = LocalDirBaselineStore(root, clock=clock_at(start))
    for i in range(1, count + 1):
        store.put(run_of(root.parent, i, eval_fingerprint=fp), "main")


def history(root: Path, fp: str = FP) -> list[str]:
    return sorted(p.name for p in (root / fp / "history").iterdir())


def test_the_three_oldest_of_twenty_three_are_removed(tmp_path: Path) -> None:
    root = tmp_path / "b"
    fill(root, 23)
    removed = prune_baselines(root, keep=20, now=NOW)
    assert sorted(removed) == [f"{FP}/history/{run_id(i)}" for i in (1, 2, 3)]
    assert history(root) == [run_id(i) for i in range(4, 24)]
    back = LocalDirBaselineStore(root).get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(23)


def test_pruning_twice_removes_nothing_the_second_time(tmp_path: Path) -> None:
    root = tmp_path / "b"
    fill(root, 23)
    prune_baselines(root, keep=20, now=NOW)
    assert prune_baselines(root, keep=20, now=NOW) == []


def test_fewer_than_keep_removes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "b"
    fill(root, 5)
    assert prune_baselines(root, keep=20, now=NOW) == []


def test_a_fingerprint_unused_for_ninety_one_days_is_removed_and_eighty_nine_is_kept(
    tmp_path: Path,
) -> None:
    root = tmp_path / "b"
    fill(root, 2, fp="a" * 16, start=NOW - timedelta(days=91))
    fill(root, 2, fp="b" * 16, start=NOW - timedelta(days=89))
    removed = prune_baselines(root, keep=20, unused_days=90, now=NOW)
    assert removed == ["a" * 16]
    assert not (root / ("a" * 16)).exists()
    assert (root / ("b" * 16) / "main").is_dir()


def test_a_release_anchor_older_than_ninety_days_is_kept(tmp_path: Path) -> None:
    root = tmp_path / "b"
    old = LocalDirBaselineStore(root, clock=clock_at(NOW - timedelta(days=200)))
    old.put(run_of(tmp_path, 1, block=1, eval_fingerprint=FP), "release-b1")
    old.put(run_of(tmp_path, 2, block=1, eval_fingerprint=FP), "nightly-b1")
    removed = prune_baselines(root, keep=20, unused_days=90, now=NOW)
    assert (root / FP / "release-b1").is_dir()
    assert not (root / FP / "nightly-b1").exists()
    assert f"{FP}/nightly-b1" in removed
    assert LocalDirBaselineStore(root).get(FP, "release-b1") is not None


def test_the_history_entry_of_a_current_baseline_is_never_pruned(tmp_path: Path) -> None:
    root = tmp_path / "b"
    store = LocalDirBaselineStore(root, clock=clock_at(NOW - timedelta(days=1)))
    store.put(run_of(tmp_path, 1, block=0, eval_fingerprint=FP), "release-b0")
    for i in range(2, 25):
        store.put(run_of(tmp_path, i, block=0, eval_fingerprint=FP), "nightly-b0")
    prune_baselines(root, keep=20, now=NOW)
    assert run_id(1) in history(root)  # still the current release-b0
    assert run_id(2) not in history(root)


def test_junk_names_and_links_are_never_followed_or_deleted(tmp_path: Path) -> None:
    root = tmp_path / "b"
    fill(root, 23)
    outside = tmp_path / "outside"
    (outside / "keep").mkdir(parents=True)
    (outside / "keep" / "file").write_text("x", encoding="utf-8")
    Path(root / FP / "history" / "20200101T000000-ffffff").symlink_to(
        outside, target_is_directory=True
    )
    Path(root / ("c" * 16)).symlink_to(outside, target_is_directory=True)
    (root / "not a fingerprint!").mkdir()
    (root / "stray-file").write_text("x", encoding="utf-8")
    prune_baselines(root, keep=20, unused_days=0, now=NOW + timedelta(days=400))
    assert (outside / "keep" / "file").read_text(encoding="utf-8") == "x"
    assert (root / "not a fingerprint!").is_dir()
    assert (root / "stray-file").is_file()


def test_a_root_that_is_not_a_directory_is_a_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="data root"):
        prune_baselines(tmp_path / "missing", keep=20, now=NOW)


@pytest.mark.parametrize("keep", [0, -1])
def test_keep_must_be_positive(tmp_path: Path, keep: int) -> None:
    (tmp_path / "b").mkdir()
    with pytest.raises(StoreError, match="keep"):
        prune_baselines(tmp_path / "b", keep=keep, now=NOW)


def test_a_naive_now_is_refused(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    with pytest.raises(StoreError, match="timezone"):
        prune_baselines(tmp_path / "b", keep=20, now=datetime(2026, 11, 2, 22, 0))  # noqa: DTZ001
