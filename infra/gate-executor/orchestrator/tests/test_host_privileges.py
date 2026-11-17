"""Host files agree (review #202, D1096): unit hardening vs sudo repair; cleanup safety."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from gate_orchestrator.preflight import RESTART

HOST = Path(__file__).resolve().parents[2] / "host"
UNIT = (HOST / "pruefstand-runner.service").read_text(encoding="utf-8")
SUDOERS = (HOST / "sudoers.d" / "pruefstand-tunnel").read_text(encoding="utf-8")
RUNNER_ENV = (HOST / "runner.env.example").read_text(encoding="utf-8")
RUNNER_DIR = "/home/pruefstand/pruefstand/runner"
HOOK_CHECKOUT = "/home/pruefstand/pruefstand-gate/"
# systemd.exec(5): each of these turns on no_new_privs, under which sudo refuses to run.
IMPLY_NO_NEW_PRIVS = (
    "NoNewPrivileges",
    "SystemCallFilter",
    "SystemCallArchitectures",
    "RestrictAddressFamilies",
    "RestrictNamespaces",
    "PrivateDevices",
    "ProtectKernelTunables",
    "ProtectKernelModules",
    "ProtectKernelLogs",
    "ProtectClock",
    "MemoryDenyWriteExecute",
    "RestrictRealtime",
    "RestrictSUIDSGID",
    "LockPersonality",
    "DynamicUser",
)


def _set(directive: str) -> bool:
    values = [
        line.split("=", 1)[1].strip()
        for line in UNIT.splitlines()
        if line.startswith(f"{directive}=")
    ]
    return any(v.lower() not in {"", "no", "false", "0", "off"} for v in values)


def test_preflight_repair_matches_the_one_sudoers_rule() -> None:
    assert RESTART[:2] == ("sudo", "-n")
    rules = [line for line in SUDOERS.splitlines() if line and not line.startswith("#")]
    assert rules == [f"pruefstand ALL=(root) NOPASSWD: /usr/bin/{' '.join(RESTART[2:])}"]


@pytest.mark.parametrize("directive", IMPLY_NO_NEW_PRIVS)
def test_unit_keeps_sudo_usable_for_the_tunnel_repair(directive: str) -> None:
    # review #202 blocker: under no_new_privs `sudo -n systemctl restart ...` fails, so a dropped
    # tunnel would never be repaired and the D226 retry would always end in error
    assert not _set(directive), directive


def test_hooks_run_from_the_stable_private_checkout_not_the_job_workspace() -> None:
    hooks = dict(
        line.split("=", 1)
        for line in RUNNER_ENV.splitlines()
        if line.startswith("ACTIONS_RUNNER_HOOK_")
    )
    assert set(hooks) == {"ACTIONS_RUNNER_HOOK_JOB_STARTED", "ACTIONS_RUNNER_HOOK_JOB_COMPLETED"}
    for path in hooks.values():
        assert path.startswith(HOOK_CHECKOUT)
        assert not path.startswith(RUNNER_DIR)
        assert ".." not in path


def _cleanup(tmp: Path, workspace: str, collections: list[str]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "deleted.log"
    listing = json.dumps({"result": {"collections": [{"name": n} for n in collections]}})
    stubs = {
        "docker": "exit 0",
        "curl": (
            f'case "$*" in *DELETE*) for a in "$@"; do last="$a"; done; echo "$last" >> {log};; '
            f"*) echo '{listing}';; esac"
        ),
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    cwd = tmp / "cwd"
    cwd.mkdir()
    (cwd / "pr_glob_victim").write_text("", encoding="utf-8")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_WORKSPACE": workspace}
    return subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(HOST / "job_cleanup.sh")],  # noqa: S607 - bash from PATH
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cleanup_wipes_a_real_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "runner" / "_work" / "pruefstand-gate"
    (ws / "sub").mkdir(parents=True)
    (ws / "sub" / "f").write_text("x", encoding="utf-8")
    proc = _cleanup(tmp_path, str(ws), [])
    assert proc.returncode == 0, proc.stderr
    assert ws.is_dir()
    assert list(ws.iterdir()) == []


@pytest.mark.parametrize("kind", ["dotdot", "symlink", "root"])
def test_cleanup_refuses_a_workspace_outside_work(tmp_path: Path, kind: str) -> None:
    work = tmp_path / "runner" / "_work"
    (work / "repo").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("x", encoding="utf-8")
    if kind == "dotdot":
        workspace = f"{work}/repo/../../../victim"
    elif kind == "symlink":
        (work / "link").symlink_to(victim)
        workspace = str(work / "link")
    else:
        (work / "keep").write_text("x", encoding="utf-8")
        workspace = f"{work}/repo/.."
        victim = work
    proc = _cleanup(tmp_path, workspace, [])
    assert proc.returncode == 0, proc.stderr
    assert "not wiped" in proc.stderr
    assert (victim / "keep").exists()


def test_collection_names_are_never_globbed(tmp_path: Path) -> None:
    ws = tmp_path / "runner" / "_work" / "r"
    ws.mkdir(parents=True)
    proc = _cleanup(tmp_path, str(ws), ["pr_*", "pr_ok", "main"])
    assert proc.returncode == 0, proc.stderr
    deleted = (tmp_path / "deleted.log").read_text(encoding="utf-8").split()
    assert [d.rsplit("/", 1)[1] for d in deleted] == ["pr_*", "pr_ok"]
