"""T0.7 CPU tests: ``setup-ssh-key.sh`` (key, config block, validation)."""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from vm_testkit import Runner, Stubs

needs_keygen = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None, reason="ssh-keygen not installed"
)
KEY = "id_ed25519_cluster"


@needs_keygen
def test_ssh_key_created_with_modes_and_one_block(run_script: Runner, tmp_path: Path) -> None:
    home = tmp_path / "h"
    args = ["--home", home, "--host", "h", "--port", "2222", "--user", "u", "--no-verify"]
    res = run_script("setup-ssh-key.sh", *args)
    assert res.rc == 0, res.err
    assert stat.S_IMODE((home / ".ssh" / KEY).stat().st_mode) == 0o600
    assert stat.S_IMODE((home / ".ssh" / f"{KEY}.pub").stat().st_mode) == 0o644
    cfg = (home / ".ssh" / "config").read_text(encoding="utf-8")
    assert cfg.count("Host cairo-s101lp") == 1
    assert "Port 2222" in cfg
    assert "User u" in cfg
    assert "HostName h" in cfg
    assert "IdentitiesOnly yes" in cfg
    assert "ExitOnForwardFailure yes" in cfg
    assert "ServerAliveInterval 30" in cfg
    assert "ServerAliveCountMax 3" in cfg
    assert "ssh-copy-id" in res.out
    assert "-p 2222" in res.out
    before = {p.name: p.read_bytes() for p in (home / ".ssh").iterdir()}
    again = run_script("setup-ssh-key.sh", *args)
    assert again.rc == 0
    assert {p.name: p.read_bytes() for p in (home / ".ssh").iterdir()} == before


@needs_keygen
def test_ssh_key_keeps_existing_block_and_key(run_script: Runner, tmp_path: Path) -> None:
    ssh = tmp_path / "h" / ".ssh"
    ssh.mkdir(parents=True)
    subprocess.run(  # noqa: S603
        [shutil.which("ssh-keygen") or "", "-q", "-t", "ed25519", "-N", "", "-f", str(ssh / KEY)],
        check=True,
    )
    cfg = (
        "Host cairo-s101lp\n    HostName real.example\n    Port 4711\n    User real\n"
        "    IdentityFile ~/.ssh/id_ed25519_cluster\n"
    )
    (ssh / "config").write_text(cfg, encoding="utf-8")
    before = {p.name: p.read_bytes() for p in ssh.iterdir()}
    res = run_script("setup-ssh-key.sh", "--home", tmp_path / "h", "--no-verify")
    assert res.rc == 0, res.err
    assert {p.name: p.read_bytes() for p in ssh.iterdir()} == before
    for missing in (
        "IdentitiesOnly",
        "ServerAliveInterval",
        "ServerAliveCountMax",
        "ExitOnForwardFailure",
    ):
        assert missing in res.out


def test_ssh_key_refuses_other_users_without_home(run_script: Runner) -> None:
    res = run_script("setup-ssh-key.sh", "--host", "h", "--port", "1", "--user", "u")
    assert res.rc == 2
    assert "pruefstand" in res.err


def test_ssh_key_new_block_needs_host_port_user(run_script: Runner, tmp_path: Path) -> None:
    res = run_script("setup-ssh-key.sh", "--home", tmp_path / "h", "--no-verify")
    assert res.rc == 2


@needs_keygen
def test_ssh_key_validates_arguments_and_home(run_script: Runner, tmp_path: Path) -> None:
    good = ["--home", tmp_path / "h", "--no-verify"]
    bad_args = [
        ["--host", "a b", "--port", "22", "--user", "u"],
        ["--host", "h", "--port", "x", "--user", "u"],
        ["--host", "h", "--port", "22", "--user", "u;rm"],
    ]
    for bad in bad_args:
        assert run_script("setup-ssh-key.sh", *good, *bad).rc == 2
    res = run_script(
        "setup-ssh-key.sh",
        "--home",
        "/home/nobody/x",
        "--no-verify",
        "--host",
        "h",
        "--port",
        "1",
        "--user",
        "u",
    )
    assert res.rc == 2
    assert "TMPDIR" in res.err


@needs_keygen
def test_ssh_key_detects_an_indented_host_line_and_uses_n_for_the_login_test(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    ssh = tmp_path / "h" / ".ssh"
    ssh.mkdir(parents=True)
    (ssh / "config").write_text("  Host cairo-s101lp\n    HostName x\n", encoding="utf-8")
    stubs.add("ssh", [("*", "", 0)])
    res = run_script("setup-ssh-key.sh", "--home", tmp_path / "h")
    assert res.rc == 0, res.err
    assert (ssh / "config").read_text(encoding="utf-8").count("Host cairo-s101lp") == 1
    assert any(" -n " in f" {c} " for c in stubs.calls("ssh"))
