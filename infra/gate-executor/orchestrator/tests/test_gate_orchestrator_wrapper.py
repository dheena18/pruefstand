"""host/gate-orchestrator (D1095): refuses to run outside a job or without the trusted main."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "host" / "gate-orchestrator"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603  (fixed argv: our wrapper)
        [bash, str(WRAPPER), "night-guard", "--event", "workflow_dispatch"],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({}, "GITHUB_WORKSPACE"),
        ({"GITHUB_WORKSPACE": "/x"}, "PRUEFSTAND_MAIN_DIR"),
        ({"GITHUB_WORKSPACE": "/x", "PRUEFSTAND_MAIN_DIR": "/nonexistent"}, "not a git checkout"),
    ],
)
def test_wrapper_refuses_without_job_or_trusted_main(env: dict[str, str], needle: str) -> None:
    done = _run(env)
    assert done.returncode != 0
    assert needle in done.stderr


def test_wrapper_runs_the_package_with_the_trusted_project() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert 'export PYTHONPATH="$ws/infra/gate-executor/orchestrator"' in text
    assert 'git -C "$main" fetch -q origin main' in text
    assert "--frozen python -m gate_orchestrator" in text
    assert os.access(WRAPPER, os.X_OK)
