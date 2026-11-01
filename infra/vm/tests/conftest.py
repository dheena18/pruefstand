"""Pytest fixtures for the T0.7 VM script tests (helpers live in ``vm_testkit``)."""

import grp
import os
import pwd
import shutil
import subprocess
from pathlib import Path

import pytest
from vm_testkit import VM_DIR, Result, Runner, Stubs
from vm_world import World, build_world


@pytest.fixture
def stubs(tmp_path: Path) -> Stubs:
    """Stub directory with only the safe real tools."""
    return Stubs(tmp_path / "stubs")


@pytest.fixture
def run_script(stubs: Stubs) -> Runner:
    """Run ``infra/vm/<script>`` with the restricted PATH; extra env via ``env=``."""

    def _run(
        script: str, *args: object, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> Result:
        full_env = {"PATH": str(stubs.bin), "HOME": str(stubs.root / "home"), "LC_ALL": "C.UTF-8"}
        full_env.update(env or {})
        proc = subprocess.run(  # noqa: S603
            [shutil.which("bash") or "bash", str(VM_DIR / script), *map(str, args)],
            env=full_env,
            capture_output=True,
            text=True,
            cwd=cwd or stubs.root,
            timeout=120,
            check=False,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    return _run


@pytest.fixture
def me() -> str:
    """``user:group`` of the user running the tests (stands in for ``pruefstand:pruefstand``)."""
    return f"{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}"


@pytest.fixture
def world(tmp_path: Path, stubs: Stubs) -> World:
    """A healthy fake VM (see ``vm_world``)."""
    return build_world(tmp_path, stubs)
