"""scripts/demo/try_e2e.sh must never stop or delete the production demo project (Opus on #241)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "demo" / "try_e2e.sh"
FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  run) exit 1 ;;
esac
exit 0
"""

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("flock") is None, reason="needs jq and flock"
)


def _run(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    models = tmp_path / "models"
    models.mkdir()
    (models / "qwen2.5-0.5b-instruct-q4_k_m.gguf").write_bytes(b"x")
    log = tmp_path / "docker.log"
    log.touch()
    full_env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log),
        "LIVE_MODEL_DIR": str(models),
        "STACK_LOCK": str(tmp_path / "stack.lock"),
        "STACK_LOCK_WAIT": "5",
        **env,
    }
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calls = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
    return result, calls


def _projects(calls: list[list[str]]) -> set[str]:
    return {c[c.index("-p") + 1] for c in calls if "-p" in c}


def test_a_failed_run_tears_down_only_its_own_project(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    assert result.returncode != 0  # the fake `docker run` fails: the EXIT trap must still clean up
    downs = [c for c in calls if "down" in c]
    assert downs, "the EXIT trap did not run compose down"
    assert _projects(calls) == {"pruefstand-demo-e2e"}
    assert all("-v" in c for c in downs)  # its own volumes go with it


def test_the_production_project_is_refused_before_any_docker_call(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, E2E_PROJECT="pruefstand-demo")
    assert result.returncode == 2
    assert "production project" in result.stderr
    assert calls == []


def test_no_docker_call_ever_names_the_production_project(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, E2E_PROJECT="pruefstand-demo-e2e-x")
    assert "pruefstand-demo" not in _projects(calls)
