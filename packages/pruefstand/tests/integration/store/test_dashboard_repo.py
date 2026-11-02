"""``push_dashboard_data`` and ``push_heartbeat`` against a local bare repository (T6.1 S9)."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from testsupport.dashboard_support import export, push
from testsupport.git_support import bare_repo, commit_count, git, show, tree_names
from testsupport.run_builders import make_manifest
from testsupport.store_support import run_id, token

from pruefstand.core.errors import StoreError
from pruefstand.core.models.dashboard import MAX_CASE_RUNS, MAX_INDEX_RUNS
from pruefstand.store.dashboard_repo import push_heartbeat

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def seed_repo(bare: Path, tmp: Path, runs: int, with_cases: int) -> None:
    """A published tree of ``runs`` runs, the newest ``with_cases`` of them with case shards."""
    work = tmp / "seed"
    git("clone", "--quiet", str(bare), str(work))
    git("checkout", "--quiet", "-b", "main", cwd=work)
    for i in range(runs):
        rid = f"2026090{i // 100 + 1}T0{i % 100 // 10}{i % 10}000-{i:06x}"
        created = T0 + timedelta(minutes=i)
        manifest = make_manifest(run_id=rid, created_at=created)
        directory = work / "runs" / rid
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        if i >= runs - with_cases:
            (directory / "report.html").write_text("<html/>", encoding="utf-8")
            (work / "cases" / rid).mkdir(parents=True)
            (work / "cases" / rid / "000.json").write_text("{}", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "seed", cwd=work)
    git("push", "--quiet", "origin", "main", cwd=work)


def test_a_sanitised_export_lands_on_main_with_index_and_manifest(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    sha = push(bare, export(tmp_path, 1))
    assert git("rev-parse", "main", git_dir=bare).strip() == sha
    names = tree_names(bare, "main")
    for expected in (
        f"runs/{run_id(1)}/run.json",
        f"runs/{run_id(1)}/results.parquet",
        f"runs/{run_id(1)}/responses.jsonl",
        f"runs/{run_id(1)}/gate.json",
        f"runs/{run_id(1)}/report.html",
        f"cases/{run_id(1)}/000.json",
        "runs/index.json",
        "manifest.json",
    ):
        assert expected in names
    assert f"runs/{run_id(1)}/manifest.json" not in names  # the export marker stays out


def test_the_repo_manifest_lists_every_file_with_a_valid_sha256(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1))
    manifest = json.loads(show(bare, "main", "manifest.json"))
    names = [n for n in tree_names(bare, "main") if n != "manifest.json"]
    assert sorted(manifest["files"]) == names
    for name, digest in manifest["files"].items():
        blob = subprocess.run(  # noqa: S603
            ["git", "--git-dir", str(bare), "show", f"main:{name}"],  # noqa: S607
            check=True,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(blob).hexdigest() == digest


def test_the_index_rows_are_copied_from_run_json_and_gate_json(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1))
    index = json.loads(show(bare, "main", "runs/index.json"))
    assert index["schema_version"] == "1"
    row = index["runs"][0]
    assert row["run_id"] == run_id(1)
    assert row["status"] == "pass"
    assert row["stack"] == "live"
    assert row["no_baseline"] is False
    assert "cost_usd" in row
    assert "block" in row
    assert "judged_subset" in row


def test_an_unsanitised_directory_is_refused_and_nothing_is_pushed(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "run.json").write_text(make_manifest().model_dump_json(), encoding="utf-8")
    with pytest.raises(StoreError, match="sanitise"):
        push(bare, plain)
    assert git("for-each-ref", git_dir=bare).strip() == ""


def test_a_file_with_a_canary_is_refused_even_when_sealed(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    leaking = export(tmp_path, 1, added={"slices.json": f'{{"x": "{token("LEAK")}"}}'.encode()})
    with pytest.raises(StoreError, match="CANARY-"):
        push(bare, leaking)
    assert git("for-each-ref", git_dir=bare).strip() == ""


def test_a_file_changed_after_sealing_is_refused(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    src = export(tmp_path, 1)
    (src / "run.json").write_text(make_manifest().model_dump_json() + " ", encoding="utf-8")
    with pytest.raises(StoreError, match="manifest"):
        push(bare, src)


def test_a_symlink_in_the_source_is_refused(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    src = export(tmp_path, 1)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (src / "link.txt").symlink_to(outside)
    with pytest.raises(StoreError, match="symlink"):
        push(bare, src)


def test_a_second_identical_push_changes_nothing(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    src = export(tmp_path, 1)
    first = push(bare, src)
    second = push(bare, src)
    assert second == first
    assert commit_count(bare, "main") == 1


def test_extra_files_are_written_and_cannot_escape_the_tree(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1), extra={"labels.json": b"{}", "meta/schema.json": b"[]"})
    names = tree_names(bare, "main")
    assert "labels.json" in names
    assert "meta/schema.json" in names
    again = export(tmp_path, 2, name="again")
    for bad in (
        "../x",
        "/etc/passwd",
        ".git/config",
        "runs/index.json",
        "manifest.json",
        "a/../../b",
    ):
        with pytest.raises(StoreError, match="extra"):
            push(bare, again, extra={bad: b"x"})


def test_the_token_never_appears_in_argv_urls_or_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    secret = "github_pat_" + "".join(chr(65 + (i * 5) % 26) for i in range(40))
    monkeypatch.setenv("DASHBOARD_DATA_PAT", secret)
    seen: list[list[str]] = []
    real = subprocess.run

    def spy(args: list[str], *a: Any, **kw: Any) -> Any:
        seen.append([str(x) for x in args])
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1))
    push_heartbeat("owner/pruefstand-dashboard-data", {"ts": "x"}, remote=str(bare))
    assert seen
    assert not any(secret in part for argv in seen for part in argv)
    out = capfd.readouterr()
    assert secret not in out.out + out.err
    assert secret not in show(bare, "main", "runs/index.json")


# --- P5.1: the whole published tree is rewritten -----------------------------------------------


def test_the_tree_is_pruned_to_200_runs_and_20_case_sets(tmp_path: Path) -> None:
    assert (MAX_INDEX_RUNS, MAX_CASE_RUNS) == (200, 20)
    bare = bare_repo(tmp_path)
    seed_repo(bare, tmp_path, runs=200, with_cases=21)
    new = export(tmp_path, 7)
    # the new run is the newest: created_at now
    push(bare, new)
    names = tree_names(bare, "main")
    run_dirs = {n.split("/")[1] for n in names if n.startswith("runs/") and n.count("/") == 2}
    case_dirs = {n.split("/")[1] for n in names if n.startswith("cases/")}
    reports = [n for n in names if n.endswith("/report.html")]
    index = json.loads(show(bare, "main", "runs/index.json"))
    assert len(run_dirs) == 200
    assert len(index["runs"]) == 200
    assert {r["run_id"] for r in index["runs"]} == run_dirs
    assert len(case_dirs) == 20
    assert len(reports) == 20
    assert run_id(7) in case_dirs
    created = [r["created_at"] for r in index["runs"]]
    assert created == sorted(created, reverse=True)
    oldest = "20260901T000000-000000"
    assert oldest not in run_dirs  # the oldest run directory is gone


def test_the_manifest_lists_exactly_the_remaining_files(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    seed_repo(bare, tmp_path, runs=30, with_cases=25)
    push(bare, export(tmp_path, 7))
    manifest = json.loads(show(bare, "main", "manifest.json"))
    names = [n for n in tree_names(bare, "main") if n != "manifest.json"]
    assert sorted(manifest["files"]) == names
    assert len([n for n in names if n.startswith("cases/")]) == 20


# --- heartbeat ---------------------------------------------------------------------------------

PAYLOAD = {
    "ts": "2026-11-02T22:00:00+00:00",
    "last_job": "nightly",
    "tunnel_ok": "true",
    "maintenance": "false",
    "drift_no_release_baseline": "true",
    "last_nightly_status": "skipped: preflight data root",
    "last_nightly_at": "2026-11-01T22:04:00+00:00",
    "tunnel_ok_false_since": "",
    "ollama_gpu0_ok_false_since": "2026-11-02T20:00:00+00:00",
}


def test_two_heartbeats_leave_one_commit_with_the_second_payload(tmp_path: Path) -> None:
    bare = bare_repo(tmp_path)
    push(bare, export(tmp_path, 1))
    main_tip = git("rev-parse", "main", git_dir=bare).strip()
    push_heartbeat("owner/data", {"ts": "first"}, remote=str(bare))
    sha = push_heartbeat("owner/data", PAYLOAD, remote=str(bare))
    assert commit_count(bare, "heartbeat") == 1
    assert git("rev-parse", "heartbeat", git_dir=bare).strip() == sha
    assert tree_names(bare, "heartbeat") == ["heartbeat.json"]
    assert json.loads(show(bare, "heartbeat", "heartbeat.json")) == PAYLOAD
    assert git("rev-parse", "main", git_dir=bare).strip() == main_tip


@pytest.mark.parametrize(
    "payload",
    [{"ts": 1}, {"": "x"}, {"a b": "x"}, {"k": "x" * 5000}, {f"k{i}": "v" for i in range(200)}],
)
def test_a_bad_heartbeat_payload_is_refused(tmp_path: Path, payload: Any) -> None:
    bare = bare_repo(tmp_path)
    with pytest.raises(StoreError, match="payload"):
        push_heartbeat("owner/data", payload, remote=str(bare))
    assert git("for-each-ref", git_dir=bare).strip() == ""
