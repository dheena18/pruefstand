"""Shared fixtures of the mutation benchmark tests (T7.1a, T7.1b)."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from mutations.schema import MUTATIONS_ROOT

REPO = MUTATIONS_ROOT.parents[1]


@pytest.fixture
def worktree(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "wt"
    yield path
    subprocess.run(  # noqa: S603
        ["git", "worktree", "remove", "--force", str(path)],  # noqa: S607
        cwd=REPO,
        check=False,
        capture_output=True,
        timeout=60,
    )
