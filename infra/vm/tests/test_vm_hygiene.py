"""T0.7 CPU tests: repo hygiene of ``infra/vm`` (ADR-0019, A12-02, no secrets, ShellCheck)."""

import os
import re
import shutil
import subprocess

import pytest
from vm_testkit import VM_DIR

SHELL_FILES = sorted(
    p for p in VM_DIR.iterdir() if p.suffix in {".sh", ".service"} or p.name == "pruefstand-lock"
)
ALL_FILES = sorted(
    p
    for p in VM_DIR.iterdir()
    if (p.is_file() and p.suffix in {".sh", ".service", ".md"}) or p.name == "pruefstand-lock"
)


def test_no_mount_unit_nfs_or_automount_anywhere() -> None:
    for path in ALL_FILES:
        text = path.read_text(encoding="utf-8")
        assert "x-systemd.automount" not in text, path
        assert "mnt-pruefstand.automount" not in text, path
        assert not re.search(r"^\S+:/\S+\s+/mnt/pruefstand\s+(nfs|cifs)", text, re.M), path
        assert "RequiresMountsFor" not in text or path.suffix != ".service", path


def test_no_ruleset_flush_nftables_or_user_systemd() -> None:
    for path in SHELL_FILES:
        text = path.read_text(encoding="utf-8")
        for bad in (
            "flush ruleset",
            "nftables.service",
            "/etc/nftables",
            "systemctl --user",
            "sshpass",
        ):
            assert bad not in text, (path, bad)


def test_no_secret_like_strings() -> None:
    pattern = re.compile(
        r"(ghp_|github_pat_[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY|password\s*=)", re.I
    )
    for path in ALL_FILES:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_no_public_tunnel_names_anywhere_in_infra_vm() -> None:
    """security.md C19 review row: a case-insensitive grep over infra/ finds no public tunnel."""
    needle = "ngr" + "ok"
    for path in VM_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".service", ".md", ".py"}:
            assert needle not in path.read_text(encoding="utf-8").lower(), path


def test_scripts_are_executable_and_strict() -> None:
    for path in SHELL_FILES:
        if path.suffix == ".service":
            continue
        assert os.access(path, os.X_OK), f"{path} must be executable"
        assert "set -euo pipefail" in path.read_text(encoding="utf-8"), path


def test_shellcheck_is_clean() -> None:
    tool = shutil.which("shellcheck")
    if tool is None:
        pytest.skip("shellcheck not installed locally (CI installs it)")
    files = [str(p) for p in SHELL_FILES if p.suffix == ".sh" or p.name == "pruefstand-lock"]
    res = subprocess.run([tool, *files], capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0, res.stdout
