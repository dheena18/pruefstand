"""``LocalDirBaselineStore``: layout, refs, atomic writes, integrity and hardening (T6.1 S4)."""

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from testsupport.run_builders import unhashed
from testsupport.store_support import FP, release_run, run_id, run_of

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.pipeline.gate import _TRUNCATED_SHARE
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.promote import JUDGE_TRUNCATED_SHARE

START = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)


def clock() -> Callable[[], datetime]:
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return START + timedelta(seconds=state["n"])

    return tick


def store_at(tmp_path: Path) -> LocalDirBaselineStore:
    return LocalDirBaselineStore(tmp_path / "baselines", clock=clock())


def block_run(tmp_path: Path, block: int, index: int = 1, **changes: Any) -> RunArtifacts:
    return run_of(tmp_path, index, block=block, eval_fingerprint=f"{block}" * 16, **changes)


def test_put_then_get_by_fingerprint_and_ref(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    run = run_of(tmp_path)
    store.put(run, "main")
    back = store.get(FP, "main")
    assert back is not None
    assert unhashed(back.results) == unhashed(run.results)
    assert back.root == tmp_path / "baselines" / FP / "main"
    assert back.results.manifest.artifact_sha256  # the stored run.json carries the hashes


def test_the_default_ref_is_main(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path))
    assert store.get(FP) is not None


def test_the_current_baseline_directory_holds_five_files_and_history_two_plus_manifest(
    tmp_path: Path,
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    base = tmp_path / "baselines" / FP
    assert sorted(p.name for p in (base / "main").iterdir()) == [
        "manifest.json",
        "responses.jsonl.zst",
        "results.parquet",
        "run.json",
        "scored.jsonl.zst",
    ]
    assert sorted(p.name for p in (base / "history" / run_id(1)).iterdir()) == [
        "manifest.json",
        "results.parquet",
        "run.json",
    ]


def test_the_manifest_lists_a_sha256_for_every_stored_file(tmp_path: Path) -> None:
    store_at(tmp_path).put(run_of(tmp_path), "main")
    directory = tmp_path / "baselines" / FP / "main"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {
        "run.json", "results.parquet", "responses.jsonl.zst", "scored.jsonl.zst",
    }  # fmt: skip
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


def test_main_and_the_block_refs_are_isolated(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    for block in range(3):
        store.put(block_run(tmp_path, block, index=10 + block), f"nightly-b{block}")
        store.put(block_run(tmp_path, block, index=20 + block), f"release-b{block}")
    assert store.get(FP, "main") is not None
    for block in range(3):
        fp = f"{block}" * 16
        nightly, release = store.get(fp, f"nightly-b{block}"), store.get(fp, f"release-b{block}")
        assert nightly is not None
        assert release is not None
        assert nightly.results.manifest.run_id == run_id(10 + block)
        assert release.results.manifest.run_id == run_id(20 + block)
        assert store.get(fp, "main") is None
        assert store.get(fp, f"nightly-b{(block + 1) % 3}") is None


@pytest.mark.parametrize(
    "ref", ["release", "nightly-b3", "release-b3", "foo", "", "../main", "main/x"]
)
def test_an_unknown_ref_is_a_store_error(tmp_path: Path, ref: str) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match="ref"):
        store.get(FP, ref)
    with pytest.raises(StoreError, match="ref"):
        store.put(run_of(tmp_path), ref)


def test_a_block_ref_needs_a_run_of_that_block(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match="block"):
        store.put(run_of(tmp_path), "nightly-b1")
    with pytest.raises(StoreError, match="block"):
        store.put(block_run(tmp_path, 2), "nightly-b1")
    with pytest.raises(StoreError, match="block"):
        store.put(block_run(tmp_path, 1), "main")
    with pytest.raises(StoreError, match="block"):
        store.put(release_run(tmp_path), "release-b1")  # the raw release run is not a projection


def test_an_unknown_fingerprint_is_none(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path), "main")
    assert store.get("f" * 16, "main") is None
    assert store_at(tmp_path / "other").get(FP) is None


def test_two_puts_return_the_newer_and_keep_both(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    store.put(run_of(tmp_path, 2), "main")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(2)
    assert sorted(p.name for p in (tmp_path / "baselines" / FP / "history").iterdir()) == [
        run_id(1),
        run_id(2),
    ]


def test_putting_the_same_run_twice_is_fine(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    store.put(run_of(tmp_path, 1), "main")
    assert store.get(FP, "main") is not None


@pytest.mark.parametrize("failing_call", [1, 2, 3])
def test_a_failed_rename_leaves_the_previous_baseline_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_call: int
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    real = os.rename
    calls = {"n": 0}

    def flaky(src: Any, dst: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == failing_call:
            msg = "disk gone"
            raise OSError(msg)
        real(src, dst, **kwargs)

    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(StoreError, match="cannot"):
        store.put(run_of(tmp_path, 2), "main")
    monkeypatch.undo()
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)
    leftovers = [p.name for p in (tmp_path / "baselines" / FP).iterdir()]
    assert not [n for n in leftovers if n.endswith((".partial", ".old"))]
    assert not (tmp_path / "baselines" / FP / "history" / run_id(2)).exists()


def test_readers_ignore_partial_directories(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    junk = tmp_path / "baselines" / FP / "main.abcd1234.partial"
    junk.mkdir()
    (junk / "run.json").write_text("{not json", encoding="utf-8")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


def test_a_missing_current_directory_after_an_interrupted_swap_is_an_error_not_none(
    tmp_path: Path,
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    base = tmp_path / "baselines" / FP
    (base / "main").rename(base / "main.cafe0123.old")
    with pytest.raises(StoreError, match="interrupted"):
        store.get(FP, "main")


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False, "stop_reason": "aborted"},
        {"complete": False, "stop_reason": "budget_exceeded"},
    ],
)
def test_an_incomplete_run_is_refused_and_the_store_is_unchanged(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    store = store_at(tmp_path)
    store.put(run_of(tmp_path, 1), "main")
    with pytest.raises(StoreError, match="complete"):
        store.put(run_of(tmp_path, 2, **changes), "main")
    back = store.get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"judge_fallback": True}, "judge fallback"),
        ({"judge_drift": True}, "judge_drift"),
        ({"judge_degraded": True}, "judge_degraded"),
        (
            {"stop_reason": "aborted", "complete": False, "infra_error": "tunnel_lost: x"},
            "complete",
        ),
        ({"counts": {"ok": 2, "judge_truncated": 2}, "judged_cases": 2}, "judge_truncated"),
    ],
)
def test_a_flagged_run_is_never_promoted(
    tmp_path: Path, changes: dict[str, Any], word: str
) -> None:
    store = store_at(tmp_path)
    with pytest.raises(StoreError, match=word):
        store.put(run_of(tmp_path, 1, **changes), "main")
    assert store.get(FP, "main") is None


def test_a_few_truncations_do_not_block_a_promotion(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    run = run_of(tmp_path, 1, counts={"ok": 2, "judge_truncated": 1}, judged_cases=100)
    store.put(run, "main")
    assert store.get(FP, "main") is not None


def test_the_truncation_share_is_the_one_of_the_gate() -> None:
    assert JUDGE_TRUNCATED_SHARE == _TRUNCATED_SHARE
