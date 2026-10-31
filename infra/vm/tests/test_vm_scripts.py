"""T0.7 CPU tests: data root, users, ssh key and the lock wrapper of ``infra/vm``."""

import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from vm_testkit import VM_DIR, Runner, Stubs, bash

DF_HEADER = "Filesystem 1024-blocks Used Available Capacity Mounted on"
DIRS = ("data", "corpus", "datasets", "baselines", "backups", "cache", "logs")
SENTINEL = ".pruefstand-data-root"


# --- data root (ADR-0019) -------------------------------------------------------------------------
def test_data_root_dry_run_lists_dirs_modes_and_sentinel(
    run_script: Runner, tmp_path: Path, me: str
) -> None:
    root = tmp_path / "pf"
    res = run_script("setup-data-root.sh", "--dry-run", "--root", root, "--owner", me)
    assert res.rc == 0, res.err
    for name in DIRS:
        assert any("mkdir" in ln and f"{root}/{name}" in ln for ln in res.out.splitlines()), name
        assert any("chmod 2775" in ln and f"{root}/{name}" in ln for ln in res.out.splitlines()), (
            name
        )
    assert f"{root}/{SENTINEL}" in res.out
    assert not root.exists(), "dry run must not create anything"


def test_data_root_second_run_changes_nothing(run_script: Runner, tmp_path: Path, me: str) -> None:
    root = tmp_path / "pf"
    first = run_script("setup-data-root.sh", "--root", root, "--owner", me)
    assert first.rc == 0, first.err
    assert (root / SENTINEL).is_file()
    assert stat.S_IMODE(root.stat().st_mode) == 0o2775
    for name in DIRS:
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o2775
    again = run_script("setup-data-root.sh", "--dry-run", "--root", root, "--owner", me)
    assert again.rc == 0
    assert "PLAN" not in again.out
    assert "no changes" in again.out


def test_data_root_keeps_existing_content_and_warns_on_low_space(
    run_script: Runner, stubs: Stubs, tmp_path: Path, me: str
) -> None:
    root = tmp_path / "pf"
    (root / "data").mkdir(parents=True)
    (root / "data" / "keep.txt").write_text("x", encoding="utf-8")
    stubs.add(
        "df",
        [
            (
                "*",
                DF_HEADER + "\n/dev/x 100 90 10485760 90% /",
                0,
            )
        ],
    )
    res = run_script("setup-data-root.sh", "--root", root, "--owner", me)
    assert res.rc == 0, res.err
    assert (root / "data" / "keep.txt").read_text(encoding="utf-8") == "x"
    assert "WARN" in res.out
    assert "free" in res.out


# --- users, groups, lock dir ----------------------------------------------------------------------
def _user_stubs(
    stubs: Stubs, *, user_exists: bool, docker_members: str, pf_members: str = ""
) -> None:
    entry = "pruefstand:x:998:998::/home/pruefstand:/bin/bash"
    stubs.add(
        "getent",
        [
            ("passwd pruefstand", entry if user_exists else "", 0 if user_exists else 2),
            ("group docker", f"docker:x:999:{docker_members}", 0),
            (
                "group pruefstand",
                f"pruefstand:x:998:{pf_members}" if user_exists else "",
                0 if user_exists else 2,
            ),
        ],
    )


def _users_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--dry-run",
        *("--owner", "alice"),
        *("--lock-dir", str(tmp_path / "lib")),
        *("--bin-dir", str(tmp_path / "bin")),
        "--home", str(tmp_path / "home"), *extra,
    ]  # fmt: skip


def test_users_dry_run_fresh_machine(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _user_stubs(stubs, user_exists=False, docker_members="alice")
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 0, res.err
    assert re.search(r"useradd --system .*pruefstand", res.out)
    assert "--home-dir /home/pruefstand" in res.out
    assert "usermod -aG pruefstand alice" in res.out
    assert "usermod -aG docker pruefstand" in res.out
    assert re.search(r"2770.*lib", res.out)
    assert re.search(r"0660.*gpu\.lock", res.out)
    assert "pruefstand-lock" in res.out
    assert "MAINTENANCE" not in res.out + res.err
    assert not (tmp_path / "lib").exists()


def test_users_existing_user_is_kept_and_shell_only_reported(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _user_stubs(stubs, user_exists=True, docker_members="alice,pruefstand", pf_members="alice")
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 0, res.err
    assert "useradd" not in res.out
    assert "usermod -aG" not in res.out
    assert "--fix-shell" in res.out
    assert "/bin/bash" in res.out
    assert "usermod --shell" not in res.out
    fixed = run_script("setup-users.sh", *_users_args(tmp_path, "--fix-shell"))
    assert "usermod --shell /usr/sbin/nologin pruefstand" in fixed.out


def test_users_refuses_to_remove_extra_docker_members_without_force(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _user_stubs(
        stubs, user_exists=True, docker_members="alice,pruefstand,mallory", pf_members="alice"
    )
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 4
    assert "mallory" in res.out + res.err
    assert "--force" in res.out + res.err
    assert "gpasswd -d" not in res.out
    forced = run_script("setup-users.sh", *_users_args(tmp_path, "--force"))
    assert forced.rc == 0
    assert "gpasswd -d mallory docker" in forced.out


def test_users_needs_an_owner(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _user_stubs(stubs, user_exists=True, docker_members="pruefstand")
    args = [a for a in _users_args(tmp_path) if a not in {"--owner", "alice"}]
    res = run_script("setup-users.sh", *args, env={"SUDO_USER": ""})
    assert res.rc == 2


# --- ssh key --------------------------------------------------------------------------------------
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


# --- pruefstand-lock (A11-01) ---------------------------------------------------------------------
def _lock_dir(tmp_path: Path) -> Path:
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "gpu.lock").touch()
    return lock_dir


def _run_lock(
    stubs: Stubs, lock_dir: Path, home: Path, *cmd: str, timeout_s: str = "5"
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": str(stubs.bin),
        "HOME": str(home),
        "PRUEFSTAND_LOCK_DIR": str(lock_dir),
        "GPU_LOCK_TIMEOUT_S": timeout_s,
    }
    return subprocess.run(  # noqa: S603
        [shutil.which("bash") or "bash", str(VM_DIR / "pruefstand-lock"), *cmd],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_lock_runs_command_with_lock_held_flag_and_returns_its_rc(
    stubs: Stubs, tmp_path: Path
) -> None:
    lock_dir = _lock_dir(tmp_path)
    ok = _run_lock(stubs, lock_dir, tmp_path / "a", "sh", "-c", 'echo "held=$PRUEFSTAND_LOCK_HELD"')
    assert ok.returncode == 0
    assert "held=1" in ok.stdout
    assert _run_lock(stubs, lock_dir, tmp_path / "a", "sh", "-c", "exit 7").returncode == 7


def test_lock_busy_exits_75_across_homes(stubs: Stubs, tmp_path: Path) -> None:
    lock_dir = _lock_dir(tmp_path)
    holder = subprocess.Popen(  # noqa: S603
        [bash(), str(VM_DIR / "pruefstand-lock"), "sh", "-c", "echo ready; sleep 20"],
        env={"PATH": str(stubs.bin), "PRUEFSTAND_LOCK_DIR": str(lock_dir), "HOME": str(tmp_path)},
        stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        res = _run_lock(stubs, lock_dir, tmp_path / "other-home", "true", timeout_s="1")
        assert res.returncode == 75
        assert "gpu.lock busy" in res.stderr
    finally:
        holder.kill()
        holder.wait()


def test_lock_without_command_or_lock_file_fails_cleanly(stubs: Stubs, tmp_path: Path) -> None:
    assert _run_lock(stubs, _lock_dir(tmp_path), tmp_path).returncode == 64
    empty = tmp_path / "empty"
    empty.mkdir()
    res = _run_lock(stubs, empty, tmp_path, "true")
    assert res.returncode == 2
    assert "setup-users.sh" in res.stderr
