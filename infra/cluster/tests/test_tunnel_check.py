"""Tests for tunnel_check.sh (T0.6 S2) with `--print-cmd`: nothing here opens an SSH connection."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feasibility" / "tunnel_check.sh"


def _print_cmd(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k != "PROBE_PORT0"}
    full_env.update(env or {})
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["bash", str(SCRIPT), *args, "--print-cmd"],  # noqa: S607  # bash from PATH
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
        timeout=20,
    )


def _ssh_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("ssh ")]


def _forwards(out: str) -> list[str]:
    return [line for line in _ssh_lines(out) if " -L " in line]


def test_default_opens_exactly_one_forward_on_21434() -> None:
    proc = _print_cmd()
    assert proc.returncode == 0, proc.stderr
    forwards = _forwards(proc.stdout)
    assert len(forwards) == 1
    assert "-L 127.0.0.1:21434:localhost:11434" in forwards[0]
    assert "ExitOnForwardFailure=yes" in forwards[0]
    assert "http://127.0.0.1:21434" in proc.stdout


def test_probe_port0_overrides_the_local_port() -> None:
    proc = _print_cmd(env={"PROBE_PORT0": "31434"})
    forwards = _forwards(proc.stdout)
    assert len(forwards) == 1
    assert "-L 127.0.0.1:31434:localhost:11434" in forwards[0]


def test_local_side_is_never_11434() -> None:
    proc = _print_cmd()
    for fwd in _forwards(proc.stdout):
        assert "127.0.0.1:11434:" not in fwd
    refused = _print_cmd(env={"PROBE_PORT0": "11434"})
    assert refused.returncode != 0
    assert "11434" in refused.stderr


def test_only_the_remote_port_11434_is_forwarded() -> None:
    forward = _forwards(_print_cmd().stdout)[0]
    assert forward.count("localhost:") == 1
    assert forward.rstrip().split()[-2].endswith(":localhost:11434")


def test_use_existing_tunnel_prints_no_forward() -> None:
    proc = _print_cmd("--use-existing-tunnel")
    assert proc.returncode == 0, proc.stderr
    assert _forwards(proc.stdout) == []
    assert "http://127.0.0.1:11434" in proc.stdout


def test_detached_check_uses_setsid_nohup_and_a_second_ssh() -> None:
    out = _print_cmd("--use-existing-tunnel").stdout
    assert "tmux" not in out
    start = [line for line in _ssh_lines(out) if "setsid nohup" in line]
    live = [line for line in _ssh_lines(out) if "kill -0" in line]
    assert len(start) == 1
    assert len(live) == 1
    assert start[0] != live[0]
    assert "-L" not in start[0].split()
    assert "-L" not in live[0].split()


@pytest.mark.parametrize("arg", ["--bogus"])
def test_unknown_argument_fails(arg: str) -> None:
    proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["bash", str(SCRIPT), arg],  # noqa: S607  # bash from PATH
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert proc.returncode != 0


def test_real_run_refuses_without_the_gpu_lock() -> None:
    env = {k: v for k, v in os.environ.items() if k != "PRUEFSTAND_LOCK_HELD"}
    proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["bash", str(SCRIPT), "--use-existing-tunnel"],  # noqa: S607  # bash from PATH
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=20,
    )
    assert proc.returncode == 2
    assert "pruefstand-lock" in proc.stderr
    assert "CHECK" not in proc.stdout
