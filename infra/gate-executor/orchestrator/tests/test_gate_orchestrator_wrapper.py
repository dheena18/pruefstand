"""host/gate-orchestrator (D1095, #224): refusals; per-job worktree; the shared HEAD stays."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "host" / "gate-orchestrator"


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


def _start(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603  (fixed argv: our wrapper)
        [_exe("bash"), str(WRAPPER), "night-guard", "--event", "workflow_dispatch"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    proc = _start({"PATH": os.environ["PATH"], **env})
    out, err = proc.communicate(timeout=60)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({}, "GITHUB_WORKSPACE"),
        ({"GITHUB_WORKSPACE": "/x"}, "PRUEFSTAND_MAIN_DIR"),
        ({"GITHUB_WORKSPACE": "/x", "PRUEFSTAND_MAIN_DIR": "/nonexistent"}, "RUNNER_TEMP"),
        (
            {
                "GITHUB_WORKSPACE": "/x",
                "PRUEFSTAND_MAIN_DIR": "/nonexistent",
                "RUNNER_TEMP": "/r",
            },
            "not a git checkout",
        ),
    ],
)
def test_wrapper_refuses_without_job_or_trusted_main(env: dict[str, str], needle: str) -> None:
    done = _run(env)
    assert done.returncode != 0
    assert needle in done.stderr


def _sandbox(tmp: Path) -> tuple[dict[str, str], Path, str]:
    """A public origin with a new main commit, a stale shared clone and a ``uv`` that logs."""
    origin, shared = tmp / "origin", tmp / "shared"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    _git(tmp, "clone", "-q", str(origin), str(shared))
    stale = _git(shared, "rev-parse", "HEAD")
    (origin / "new.txt").write_text("two\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "two")
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    log = tmp / "uv.log"
    uv.write_text(
        f'#!/bin/sh\necho "$PYTHONPATH $*" >> {log}\necho "main=$PRUEFSTAND_MAIN_DIR" >> {log}\n'
        f'ls "$3/new.txt" >> {log}\nsleep 1\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    (tmp / "runner").mkdir()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(tmp / "ws"),
        "PRUEFSTAND_MAIN_DIR": str(shared),
        "RUNNER_TEMP": str(tmp / "runner"),
        "HOME": str(tmp),
    }
    return env, shared, stale


def test_overlapping_calls_run_from_their_own_worktree_and_never_move_the_shared_head(
    tmp_path: Path,
) -> None:
    env, shared, stale = _sandbox(tmp_path)
    first, second = _start(env), _start(env)
    time.sleep(0.2)
    assert _git(shared, "rev-parse", "HEAD") == stale  # while both run
    for proc in (first, second):
        _, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
    assert _git(shared, "rev-parse", "HEAD") == stale
    log = (tmp_path / "uv.log").read_text(encoding="utf-8").splitlines()
    runs = [line for line in log if " run --project " in line]
    assert len(runs) == 2
    assert all(
        line.startswith(f"{tmp_path / 'ws'}/infra/gate-executor/orchestrator ") for line in runs
    )
    assert len({line.split()[3] for line in runs}) == 2  # two different worktrees
    assert sum(line.endswith("new.txt") for line in log) == 2  # both at the fetched main
    worktrees = sorted(line.split()[3] for line in runs)
    mains = sorted(line.removeprefix("main=") for line in log if line.startswith("main="))
    assert mains == worktrees  # the Python side reads config and health.sh from the worktree
    assert _git(shared, "worktree", "list").count("\n") == 0  # both removed again
    assert list((tmp_path / "runner").iterdir()) == []
