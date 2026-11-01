"""Tests for scripts/check_no_raw_data.py (T2.1 S7, round 9 X1.3)."""

from pathlib import Path

import pytest
from check_no_raw_data import ALLOWLIST, find_violations, main

MB = 1024 * 1024


def _tracked(root: Path, rel: str, size: int = 10) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return rel


def test_allowlist_is_exactly_the_five_x13_patterns() -> None:
    assert set(ALLOWLIST) == {
        "results/**",
        "experiments/**/results/**",
        "apps/dashboard/fixtures/**",
        "datasets/fixtures/**",
        "tests/**/fixtures/**",
    }
    assert len(ALLOWLIST) == 5


def test_parquet_at_repo_root_fails(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "foo.parquet")
    assert find_violations(tmp_path, [rel])


def test_parquet_in_datasets_fixtures_passes(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "datasets/fixtures/foo.parquet")
    assert find_violations(tmp_path, [rel]) == []


@pytest.mark.parametrize(
    ("rel", "size"),
    [
        ("results/_inputs/rq3/x.parquet", 500 * 1024),
        ("experiments/rq1/results/grid.parquet", 10),
        ("apps/dashboard/fixtures/populated/runs/r1/results.parquet", 10),
        ("tests/e2e/fixtures/x.parquet", 10),
        ("packages/pruefstand/tests/fixtures/runs/r.parquet", 10),
    ],
)
def test_allowlisted_parquet_passes(tmp_path: Path, rel: str, size: int) -> None:
    _tracked(tmp_path, rel, size)
    assert find_violations(tmp_path, [rel]) == []


def test_size_limit_applies_inside_allowlist(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "results/_inputs/rq3/x.parquet", 2 * MB)
    assert find_violations(tmp_path, [rel])


@pytest.mark.parametrize("rel", ["packages/x.parquet", "docs/x.arrow", "data/a.xml.zip"])
def test_data_files_outside_allowlist_fail(tmp_path: Path, rel: str) -> None:
    _tracked(tmp_path, rel)
    assert find_violations(tmp_path, [rel])


@pytest.mark.parametrize(
    "rel",
    [
        "data/raw/github/memerag/de.jsonl",
        "results/memerag/summary.csv",
        "datasets/fixtures/memerag/de.jsonl",
        "datasets/fixtures/MEMERAG/x.txt",
    ],
)
def test_memerag_path_component_fails_everywhere(tmp_path: Path, rel: str) -> None:
    _tracked(tmp_path, rel)
    assert find_violations(tmp_path, [rel])


def test_memerag_as_part_of_a_longer_name_is_not_a_component(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "docs/memerag-notes.md")
    assert find_violations(tmp_path, [rel]) == []


def test_lock_files_exempt_from_size(tmp_path: Path) -> None:
    rels = [_tracked(tmp_path, "uv.lock", 2 * MB), _tracked(tmp_path, "pnpm-lock.yaml", 2 * MB)]
    assert find_violations(tmp_path, rels) == []


def test_big_ordinary_file_fails(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "docs/big.txt", 2 * MB)
    assert find_violations(tmp_path, [rel])


def test_missing_tracked_file_is_ignored(tmp_path: Path) -> None:
    assert find_violations(tmp_path, ["gone.txt"]) == []


def test_main_prints_ok_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = _tracked(tmp_path, "docs/a.md")
    assert main(["--root", str(tmp_path)], tracked=[ok]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    bad = _tracked(tmp_path, "foo.parquet")
    assert main(["--root", str(tmp_path)], tracked=[bad]) == 1
    assert "foo.parquet" in capsys.readouterr().out


def test_lock_file_exemption_is_anchored_at_repo_root(tmp_path: Path) -> None:
    rel = _tracked(tmp_path, "packages/x/uv.lock", 2 * MB)
    assert find_violations(tmp_path, [rel])
