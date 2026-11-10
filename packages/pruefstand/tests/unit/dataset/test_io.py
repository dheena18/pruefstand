"""``dataset.io``: JSONL per split (sorted ids, sorted keys) and the manifest (T4.1 S4)."""

import json
import os
import stat
from pathlib import Path

import pytest
from testsupport.dataset_support import CORPUS, answerable_clusters, case

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import (
    build_manifest,
    read_dataset,
    read_split,
    write_dataset,
    write_split_file,
)


def _cases() -> list[TestCase]:
    return [c.model_copy(update={"split": Split.CORE}) for c in answerable_clusters(5)[::-1]] + [
        case("x-ü", "doc-ä", category=Category.UNANSWERABLE)
    ]


def test_write_then_read_round_trips_and_sorts_by_id(tmp_path: Path) -> None:
    cases = _cases()
    manifest = build_manifest("n", "v1", CORPUS, cases, seed=4)
    write_dataset(tmp_path, cases, manifest)
    lines = (tmp_path / "core.jsonl").read_text(encoding="utf-8").splitlines()
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == sorted(ids)
    assert list(json.loads(lines[0])) == sorted(json.loads(lines[0]))
    assert "doc-ä" in (tmp_path / "core.jsonl").read_text(encoding="utf-8")
    loaded = read_dataset(tmp_path)
    assert loaded.problems == []
    assert sorted(loaded.cases[Split.CORE], key=lambda c: c.id) == sorted(cases, key=lambda c: c.id)
    assert loaded.manifest is not None
    assert loaded.manifest.assignment_seed == 4
    assert loaded.manifest.splits == {Split.CORE: 6}


def test_writing_twice_is_byte_identical(tmp_path: Path) -> None:
    cases = _cases()
    manifest = build_manifest("n", "v1", CORPUS, cases, seed=1)
    write_dataset(tmp_path / "a", cases, manifest)
    write_dataset(tmp_path / "b", cases[::-1], manifest)
    for name in ("core.jsonl", "dataset_manifest.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_read_split_names_file_and_line_of_every_bad_row(tmp_path: Path) -> None:
    path = tmp_path / "core.jsonl"
    good = _cases()[0].model_dump_json()
    path.write_text(f"{good}\n\nnot json\n{good}\n" + '{"id": "x"}\n', encoding="utf-8")
    cases, problems = read_split(path)
    assert len(cases) == 2
    assert [p.split(":")[1] for p in problems] == ["3", "5"]
    assert all(p.startswith("core.jsonl:") for p in problems)


def test_a_symlinked_split_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.jsonl"
    real.write_text("", encoding="utf-8")
    (tmp_path / "core.jsonl").symlink_to(real)
    _, problems = read_split(tmp_path / "core.jsonl")
    assert problems


def test_missing_manifest_is_a_problem_not_an_exception(tmp_path: Path) -> None:
    assert read_dataset(tmp_path).problems


def test_a_split_file_is_replaced_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = _cases()
    path = tmp_path / "core.jsonl"
    write_split_file(path, cases)
    before = path.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["core.jsonl"]  # no temp file left

    def broken(self: Path, target: Path) -> Path:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        write_split_file(path, cases[:2])
    assert path.read_bytes() == before  # the old file is intact
    assert sorted(p.name for p in tmp_path.iterdir()) == ["core.jsonl"]  # the temp file is gone


def test_split_files_get_the_umask_mode_and_an_existing_mode_is_kept(tmp_path: Path) -> None:
    cases = _cases()
    old = os.umask(0o002)
    try:
        fresh = tmp_path / "fresh.jsonl"
        write_split_file(fresh, cases)
        assert stat.S_IMODE(fresh.stat().st_mode) == 0o664
        kept = tmp_path / "kept.jsonl"
        kept.write_text("x\n", encoding="utf-8")
        kept.chmod(0o644)
        write_split_file(kept, cases)
        assert stat.S_IMODE(kept.stat().st_mode) == 0o644
    finally:
        os.umask(old)
