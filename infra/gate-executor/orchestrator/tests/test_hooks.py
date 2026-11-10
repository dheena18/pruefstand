"""Static checks of the executor host files (T6.2a S9; A13-M9, ADR-0019, D100, D200)."""

import re
from pathlib import Path

import pytest

HOST = Path(__file__).resolve().parents[2] / "host"
UNIT = (HOST / "pruefstand-runner.service").read_text(encoding="utf-8")
CLEANUP = (HOST / "job_cleanup.sh").read_text(encoding="utf-8")


def _directives(name: str) -> list[str]:
    return [line.split("=", 1)[1] for line in UNIT.splitlines() if line.startswith(f"{name}=")]


def test_exec_start_is_run_sh_and_never_the_listener() -> None:
    assert _directives("ExecStart") == ["/home/pruefstand/actions-runner/run.sh"]
    assert "Runner.Listener" not in UNIT
    assert "--disableupdate" not in "".join(
        p.read_text(encoding="utf-8") for p in HOST.rglob("*") if p.is_file()
    )


def test_system_unit_as_pruefstand_restart_always_no_mount_dependency() -> None:
    assert _directives("User") == ["pruefstand"]
    assert _directives("Restart") == ["always"]
    assert "docker.service" in _directives("Requires")[0]
    for key in ("Wants", "After", "Requires", "BindsTo"):
        for value in _directives(key):
            assert "mnt-" not in value
            assert ".mount" not in value


def test_runner_env_points_both_hooks_at_the_shipped_scripts() -> None:
    env = dict(
        line.split("=", 1)
        for line in (HOST / "runner.env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert env["ACTIONS_RUNNER_HOOK_JOB_STARTED"].endswith("/host/job_started.sh")
    assert env["ACTIONS_RUNNER_HOOK_JOB_COMPLETED"].endswith("/host/job_completed.sh")
    for hook in ("job_started.sh", "job_completed.sh"):
        assert "job_cleanup.sh" in (HOST / hook).read_text(encoding="utf-8")


def test_cleanup_removes_only_labelled_pr_resources() -> None:
    docker_rm = re.findall(r"docker \w+ ls -q[^|]*|docker ps -aq[^|]*", CLEANUP)
    assert len(docker_rm) == 3
    assert all("--filter label=pruefstand.job" in cmd for cmd in docker_rm)
    assert "docker system prune" not in CLEANUP
    assert "pr_*) curl" in CLEANUP
    assert "-name 'pr-*'" in CLEANUP
    for forbidden in ("baselines", "Models", "/var/lib/pruefstand", "profile dev"):
        assert forbidden not in CLEANUP.split("set -euo pipefail", 1)[1]


@pytest.mark.parametrize("script", ["job_cleanup.sh", "job_started.sh", "job_completed.sh"])
def test_scripts_are_strict_bash(script: str) -> None:
    text = (HOST / script).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


def test_sudoers_grants_only_the_tunnel_restart() -> None:
    rules = [
        line
        for line in (HOST / "sudoers.d/pruefstand-tunnel").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert rules == ["pruefstand ALL=(root) NOPASSWD: /usr/bin/systemctl restart pruefstand-tunnel"]
