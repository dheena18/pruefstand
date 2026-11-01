"""T0.7 CPU tests: data root, users, ssh key and the lock wrapper of ``infra/vm``."""

import re
import stat
from pathlib import Path

from vm_testkit import Runner, Stubs

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


# --- review hardening (M-minors) ------------------------------------------------------------------
def test_data_root_refuses_symlinks(run_script: Runner, tmp_path: Path, me: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "pf"
    link.symlink_to(real)
    res = run_script("setup-data-root.sh", "--dry-run", "--root", link, "--owner", me)
    assert res.rc == 3
    assert "symlink" in res.err
    root = tmp_path / "ok"
    (root / "data").parent.mkdir()
    (root / "data").symlink_to(real)
    assert run_script("setup-data-root.sh", "--dry-run", "--root", root, "--owner", me).rc == 3


def test_users_refuses_a_symlinked_lock_dir(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _user_stubs(stubs, user_exists=True, docker_members="alice,pruefstand", pf_members="alice")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "lib").symlink_to(tmp_path / "elsewhere")
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 3
    assert "symlink" in res.err


def test_users_fixes_an_existing_lock_file_through_the_descriptor(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _user_stubs(stubs, user_exists=True, docker_members="alice,pruefstand", pf_members="alice")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "gpu.lock").touch()
    (tmp_path / "lib" / "gpu.lock").chmod(0o644)
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 0, res.err
    assert "chmod 0660 /proc/self/fd/8" in res.out
    assert str(tmp_path / "lib" / "gpu.lock") not in "".join(
        ln for ln in res.out.splitlines() if "chmod" in ln or "chown" in ln
    )


def test_users_refuses_a_lock_file_that_is_not_the_one_it_opened(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _user_stubs(stubs, user_exists=True, docker_members="alice,pruefstand", pf_members="alice")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "gpu.lock").touch()
    stubs.add(
        "stat",
        [
            ("-L -c %d:%i /proc/self/fd/8", "64:1", 0),
            ("-c %d:%i *gpu.lock", "64:2", 0),
            ("-c %a %U:%G *lib", "2770 pruefstand:pruefstand", 0),
            ("*", "660 pruefstand:pruefstand", 0),
        ],
    )
    res = run_script("setup-users.sh", *_users_args(tmp_path))
    assert res.rc == 3
    assert "changed" in res.err
