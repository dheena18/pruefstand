"""mirror_fork_pr.sh (T6.2b S2, X2.3, P1.2): a local bare repo stands in for GitHub's PR refs."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "mirror_fork_pr.sh"
DISPATCH = "gh workflow run gate-executor.yml -R dheena18/pruefstand-gate -f pr=7"


def _exe(name: str) -> str:
    path = shutil.which(name)
    assert path is not None, name
    return path


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603  (fixed argv: git with test paths)
        [_exe("git"), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return done.stdout.strip()


def _setup(tmp: Path, changed: str) -> tuple[Path, Path, str]:
    """Bare `origin` with main and refs/pull/7/head changing ``changed``; a clone to run in."""
    origin, work = tmp / "origin.git", tmp / "work"
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp, "clone", "-q", str(origin), str(work))
    (work / "README.md").write_text("Prüfstand\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "HEAD:main")
    path = work / changed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Änderung\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "fork change")
    head = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "origin", "HEAD:refs/pull/7/head")
    _git(work, "reset", "-q", "--hard", "origin/main")
    return origin, work, head


def _run(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (fixed argv: our script)
        [_exe("bash"), str(SCRIPT), *args],
        cwd=work,
        env={"PATH": os.environ["PATH"], "HOME": str(work)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "changed",
    [
        ".github/workflows/x.yml",
        "scripts/mirror_fork_pr.sh",
        "infra/gate-executor/orchestrator/x.py",
        "infra/runner/x.sh",
        "action/action.yml",
    ],
)
def test_protected_path_is_refused(tmp_path: Path, changed: str) -> None:
    origin, work, _ = _setup(tmp_path, changed)
    proc = _run(work, "7", "--reviewed")
    assert proc.returncode == 1
    assert "refused" in proc.stderr
    assert _git(tmp_path, "--git-dir", str(origin), "branch", "--list", "gate/*") == ""


def test_clean_diff_without_reviewed_is_not_pushed(tmp_path: Path) -> None:
    origin, work, _ = _setup(tmp_path, "packages/pruefstand/src/x.py")
    proc = _run(work, "7")
    assert proc.returncode == 1
    assert "--reviewed" in proc.stderr
    assert _git(tmp_path, "--git-dir", str(origin), "branch", "--list", "gate/*") == ""


def test_reviewed_clean_diff_pushes_gate_branch_and_prints_dispatch(tmp_path: Path) -> None:
    origin, work, head = _setup(tmp_path, "packages/pruefstand/src/x.py")
    proc = _run(work, "7", "--reviewed")
    assert proc.returncode == 0, proc.stderr
    assert _git(tmp_path, "--git-dir", str(origin), "rev-parse", "gate/pr-7") == head
    assert DISPATCH in proc.stdout
    assert "gh pr create" not in proc.stdout + proc.stderr
    assert "--add-label" not in proc.stdout + proc.stderr


def test_dry_run_pushes_nothing(tmp_path: Path) -> None:
    origin, work, head = _setup(tmp_path, "docs/x.md")
    proc = _run(work, "7", "--reviewed", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert f"+{head}:refs/heads/gate/pr-7" in proc.stdout
    assert DISPATCH in proc.stdout
    assert _git(tmp_path, "--git-dir", str(origin), "branch", "--list", "gate/*") == ""


@pytest.mark.parametrize("args", [[], ["x"], ["0"], ["7", "--bogus"], ["7;id"]])
def test_usage_errors(tmp_path: Path, args: list[str]) -> None:
    assert _run(tmp_path, *args).returncode == 64


def test_moving_a_protected_file_out_is_refused(tmp_path: Path) -> None:
    # review #214: with rename detection, `git mv .github/workflows/x.yml docs/` lists only docs/
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / ".github" / "workflows").mkdir(parents=True)
    (work / ".github" / "workflows" / "x.yml").write_text(
        "name: x\non: push\n" * 20, encoding="utf-8"
    )
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "HEAD:main")
    (work / "docs").mkdir()
    _git(work, "mv", ".github/workflows/x.yml", "docs/x.yml")
    _git(work, "commit", "-q", "-m", "move")
    _git(work, "push", "-q", "origin", "HEAD:refs/pull/7/head")
    _git(work, "reset", "-q", "--hard", "origin/main")
    proc = _run(work, "7", "--reviewed")
    assert proc.returncode == 1
    assert ".github/workflows/x.yml" in proc.stderr
    assert _git(tmp_path, "--git-dir", str(origin), "branch", "--list", "gate/*") == ""
