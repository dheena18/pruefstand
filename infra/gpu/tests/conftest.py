"""Fixtures for the T3.1a VM-script and catalogue tests (helpers live in ``gpu_testkit``)."""

from pathlib import Path

import pytest
from gpu_repo import Repo, make_repo
from gpu_world import GpuWorld
from vm_testkit import Stubs


@pytest.fixture
def stubs(tmp_path: Path) -> Stubs:
    """Stub directory with only the safe real tools."""
    return Stubs(tmp_path / "stubs")


@pytest.fixture
def gpu(tmp_path: Path, stubs: Stubs) -> GpuWorld:
    """A healthy fake VM + cluster for the VM scripts (see ``gpu_testkit.GpuWorld``)."""
    return GpuWorld(tmp_path / "world", stubs)


@pytest.fixture
def repo(tmp_path: Path, stubs: Stubs) -> Repo:
    """A clean temp git checkout (local bare origin) with the installer and deploy scripts."""
    return make_repo(tmp_path, stubs)
