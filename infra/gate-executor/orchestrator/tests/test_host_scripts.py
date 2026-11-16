"""install_runner.sh and check-host.sh (T6.2a S9, D1021) with stubbed system commands."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

HOST = Path(__file__).resolve().parents[2] / "host"
OK_STUBS = {
    "id": 'case "$1" in -un) echo pruefstand;; -nG) echo "pruefstand docker";; esac',
    "getent": "echo docker:x:999:pruefstand,owner",
    "stat": 'echo "660 pruefstand"',
    "systemctl": "exit 0",
    "curl": 'echo \'{"models": []}\'',
    "df": 'printf "Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 1 1 52428800 1%% /mnt\\n"',
    "ssh": "exit 0",
    "ip": 'echo "    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0"',
    "docker": "echo 10.231.0.0/24",
    "ss": 'printf "LISTEN 0 128 127.0.0.1:11434 0.0.0.0:*\\nLISTEN 0 128 172.17.0.1:11434 0.0.0.0:*\\n"',
}


def _bin(tmp: Path, overrides: dict[str, str]) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {**OK_STUBS, **overrides}.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _check(tmp: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    lock = tmp / "lock"
    lock.mkdir(exist_ok=True)
    (lock / "gpu.lock").write_text("", encoding="utf-8")
    data = tmp / "data"
    data.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PATH": f"{_bin(tmp, overrides)}:{os.environ['PATH']}",
        "LOCK_DIR": str(lock),
        "PRUEFSTAND_DATA_ROOT": str(data),
        "OWNER_USER": "owner",
    }
    return subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(HOST / "check-host.sh")],  # noqa: S607 - bash from PATH
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_healthy_host_passes_every_check(tmp_path: Path) -> None:
    res = _check(tmp_path)
    assert res.returncode == 0, res.stdout
    rows = [line.split(",", 2) for line in res.stdout.splitlines()]
    assert {r[1] for r in rows} == {"OK"}
    assert len(rows) == 11


@pytest.mark.parametrize(
    ("stub", "body", "check"),
    [
        ("getent", "echo docker:x:999:pruefstand,owner,intruder", "docker-members"),
        ("stat", 'echo "666 pruefstand"', "gpu-lock"),
        ("systemctl", "exit 3", "units"),
        ("ss", 'printf "LISTEN 0 128 0.0.0.0:11434 0.0.0.0:*\\n"', "tunnel-binds"),
        ("docker", "echo 10.99.0.0/24", "proxy-egress"),
        ("df", 'printf "h\\n/dev/x 1 1 1024 1%% /mnt\\n"', "data-root"),
        ("id", 'case "$1" in -un) echo dheena;; -nG) echo "dheena";; esac', "user"),
    ],
)
def test_each_failure_is_a_fail_row_and_exit_1(tmp_path: Path, stub: str, body: str, check: str) -> None:
    res = _check(tmp_path, **{stub: body})
    assert res.returncode == 1
    failed = [line.split(",", 2)[0] for line in res.stdout.splitlines() if ",FAIL," in line]
    assert check in failed


def _install(tmp: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{_bin(tmp, {})}:{os.environ['PATH']}",
        "RUNNER_DIR": str(tmp / "runner"),
        "INSTALL_DRY_RUN": "1",
        "RUNNER_VERSION": "2.300.0",
        "RUNNER_SHA256": "0" * 64,
        **env_extra,
    }
    return subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(HOST / "install_runner.sh")],  # noqa: S607 - bash from PATH
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_is_persistent_auto_updating_and_never_takes_a_token_argument(tmp_path: Path) -> None:
    res = _install(tmp_path)
    assert res.returncode == 0, res.stderr
    config = next(line for line in res.stdout.splitlines() if "./config.sh" in line)
    assert "--labels a40" in config
    code = "\n".join(
        line
        for line in (HOST / "install_runner.sh").read_text("utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in ("--ephemeral", "--disableupdate", "--token", "--unattended"):
        assert forbidden not in res.stdout
        assert forbidden not in code
    assert "sha256sum -c" in res.stdout
    assert "actions-runner-linux-x64-2.300.0.tar.gz" in res.stdout


@pytest.mark.parametrize(
    "env",
    [{"RUNNER_VERSION": "latest"}, {"RUNNER_SHA256": "abc"}],
)
def test_install_needs_a_pinned_version_and_hash(tmp_path: Path, env: dict[str, str]) -> None:
    assert _install(tmp_path, **env).returncode == 2


def test_install_refuses_another_user(tmp_path: Path) -> None:
    (_bin(tmp_path, {"id": "echo dheena"}))
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "INSTALL_DRY_RUN": "1"}
    res = subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(HOST / "install_runner.sh")],  # noqa: S607 - bash from PATH
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2
    assert "pruefstand" in res.stderr
