"""Fixtures for the T3.1a cluster-script tests (helpers live in ``gpu_testkit``)."""

from pathlib import Path

import pytest
from gpu_repo import Repo, make_repo
from gpu_testkit import ClusterWorld
from vm_testkit import Stubs


@pytest.fixture
def stubs(tmp_path: Path) -> Stubs:
    """Stub directory with only the safe real tools."""
    return Stubs(tmp_path / "stubs")


@pytest.fixture
def world(tmp_path: Path, stubs: Stubs) -> ClusterWorld:
    """A fake cluster account (bin dir, ``cluster.env``, HOME with ``start-ollama.sh``, /proc)."""
    return ClusterWorld(tmp_path / "cluster", stubs)


@pytest.fixture
def repo(tmp_path: Path, stubs: Stubs) -> Repo:
    """A clean temp git checkout (local bare origin) holding the installer, deploy and cluster scripts."""
    return make_repo(tmp_path, stubs)
