"""The merge-and-prune rewrite of the published tree and the repo size check (T6.1, D300)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from testsupport.run_builders import make_manifest

from pruefstand.core.errors import StoreError
from pruefstand.store._dashboard_tree import rewrite_tree
from pruefstand.store.dashboard_repo import MAX_REPO_KB, check_repo_size

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def rid(i: int) -> str:
    return f"20261001T{i // 60:02d}{i % 60:02d}00-{i:06x}"


def add_run(root: Path, i: int, *, cases: bool = True, created: datetime | None = None) -> None:
    manifest = make_manifest(run_id=rid(i), created_at=created or T0 + timedelta(minutes=i))
    directory = root / "runs" / rid(i)
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    if cases:
        (directory / "report.html").write_text("<html/>", encoding="utf-8")
        (root / "cases" / rid(i)).mkdir(parents=True)
        (root / "cases" / rid(i) / "000.json").write_text("{}", encoding="utf-8")


def files(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    )


def test_only_the_newest_runs_stay_and_only_the_newest_keep_their_cases(tmp_path: Path) -> None:
    for i in range(6):
        add_run(tmp_path, i)
    rows = rewrite_tree(tmp_path, max_index=4, max_cases=2)
    assert [r["run_id"] for r in rows] == [rid(5), rid(4), rid(3), rid(2)]
    names = files(tmp_path)
    assert not any(rid(0) in n or rid(1) in n for n in names)
    assert sorted(n for n in names if n.startswith("cases/")) == [
        f"cases/{rid(4)}/000.json",
        f"cases/{rid(5)}/000.json",
    ]
    assert sorted(n for n in names if n.endswith("report.html")) == [
        f"runs/{rid(4)}/report.html",
        f"runs/{rid(5)}/report.html",
    ]


def test_the_manifest_lists_exactly_the_remaining_files(tmp_path: Path) -> None:
    for i in range(4):
        add_run(tmp_path, i)
    (tmp_path / "labels.json").write_text("{}", encoding="utf-8")
    rewrite_tree(tmp_path, max_index=3, max_cases=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(manifest["files"]) == [n for n in files(tmp_path) if n != "manifest.json"]
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


def test_a_second_rewrite_changes_nothing(tmp_path: Path) -> None:
    for i in range(4):
        add_run(tmp_path, i)
    rewrite_tree(tmp_path, max_index=3, max_cases=2)
    before = {n: (tmp_path / n).read_bytes() for n in files(tmp_path)}
    rewrite_tree(tmp_path, max_index=3, max_cases=2)
    assert {n: (tmp_path / n).read_bytes() for n in files(tmp_path)} == before


def test_equal_timestamps_are_ordered_by_run_id(tmp_path: Path) -> None:
    for i in range(3):
        add_run(tmp_path, i, created=T0)
    rows = rewrite_tree(tmp_path, max_index=2, max_cases=2)
    assert [r["run_id"] for r in rows] == [rid(2), rid(1)]


def test_a_run_directory_without_a_valid_run_json_is_skipped_not_deleted(tmp_path: Path) -> None:
    add_run(tmp_path, 1)
    broken = tmp_path / "runs" / "broken"
    broken.mkdir()
    (broken / "run.json").write_text("{not json", encoding="utf-8")
    rows = rewrite_tree(tmp_path)
    assert [r["run_id"] for r in rows] == [rid(1)]
    assert (broken / "run.json").is_file()  # kept for a human; pruned by count and age only


def test_a_directory_name_that_differs_from_the_run_id_is_skipped_not_deleted(
    tmp_path: Path,
) -> None:
    add_run(tmp_path, 1)
    (tmp_path / "runs" / rid(1)).rename(tmp_path / "runs" / rid(2))
    assert rewrite_tree(tmp_path) == []
    assert (tmp_path / "runs" / rid(2) / "run.json").is_file()


def test_orphan_case_directories_are_removed(tmp_path: Path) -> None:
    add_run(tmp_path, 1, cases=False)
    (tmp_path / "cases" / "20200101T000000-000000").mkdir(parents=True)
    (tmp_path / "cases" / "20200101T000000-000000" / "000.json").write_text("{}", encoding="utf-8")
    rewrite_tree(tmp_path)
    assert not (tmp_path / "cases" / "20200101T000000-000000").exists()


def test_the_index_rows_copy_run_json_and_gate_json(tmp_path: Path) -> None:
    add_run(tmp_path, 1)
    gate = {"status": "fail", "baseline_run_id": rid(0), "no_baseline": False}
    (tmp_path / "runs" / rid(1) / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
    add_run(tmp_path, 2)
    rows = {r["run_id"]: r for r in rewrite_tree(tmp_path)}
    assert rows[rid(1)]["status"] == "fail"
    assert rows[rid(1)]["baseline_run_id"] == rid(0)
    assert rows[rid(2)]["status"] is None
    assert rows[rid(2)]["no_baseline"] is False
    document = json.loads((tmp_path / "runs" / "index.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == "1"
    assert document["runs"] == rows_in_order(rows)


def rows_in_order(rows: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows.values(), key=lambda r: (str(r["created_at"]), str(r["run_id"])), reverse=True
    )


def test_a_symlink_in_the_tree_is_refused(tmp_path: Path) -> None:
    add_run(tmp_path, 1)
    (tmp_path / "evil").symlink_to(tmp_path / "runs", target_is_directory=True)
    with pytest.raises(StoreError, match="symlink"):
        rewrite_tree(tmp_path)


def test_the_git_directory_is_neither_listed_nor_touched(tmp_path: Path) -> None:
    add_run(tmp_path, 1)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    rewrite_tree(tmp_path)
    assert (tmp_path / ".git" / "HEAD").is_file()
    assert not any(
        n.startswith(".git") for n in json.loads((tmp_path / "manifest.json").read_text())["files"]
    )


def test_an_empty_tree_gets_an_empty_index(tmp_path: Path) -> None:
    assert rewrite_tree(tmp_path) == []
    assert json.loads((tmp_path / "runs" / "index.json").read_text(encoding="utf-8"))["runs"] == []


# --- repository size (UI13-12) -----------------------------------------------------------------


@respx.mock
def test_a_small_repository_passes() -> None:
    respx.get("https://api.github.com/repos/o/data").respond(200, json={"size": 5_000})
    check_repo_size("o/data", None)


@respx.mock
def test_a_repository_above_one_gigabyte_fails() -> None:
    respx.get("https://api.github.com/repos/o/data").respond(200, json={"size": MAX_REPO_KB + 1})
    with pytest.raises(StoreError, match="1 GB"):
        check_repo_size("o/data", None)


@respx.mock
def test_exactly_one_gigabyte_still_passes() -> None:
    respx.get("https://api.github.com/repos/o/data").respond(200, json={"size": MAX_REPO_KB})
    check_repo_size("o/data", None)


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"size": "big"}),
        httpx.Response(404),
    ],
)
def test_an_unavailable_size_does_not_block_the_push(response: httpx.Response) -> None:
    respx.get("https://api.github.com/repos/o/data").mock(return_value=response)
    check_repo_size("o/data", None)


@respx.mock
def test_a_network_failure_does_not_block_the_push() -> None:
    respx.get("https://api.github.com/repos/o/data").mock(side_effect=httpx.ConnectError("down"))
    check_repo_size("o/data", None)


@respx.mock
def test_the_token_goes_into_the_authorization_header_only() -> None:
    route = respx.get("https://api.github.com/repos/o/data").respond(200, json={"size": 1})
    check_repo_size("o/data", "tok-" + "x" * 20)
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tok-" + "x" * 20
    assert "tok-" not in str(request.url)
