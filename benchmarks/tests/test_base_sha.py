"""Every mutation patch applies at ``base_sha`` (T7.1a S4; follow-up T7.1c, D1290).

``apply.py`` creates its worktree at ``index.base_sha`` and applies the patch there, so a patch that
only applies to the current tree breaks the RQ3 bench (it did for N01 after D1288). This test checks
out ``base_sha`` in a temporary worktree and runs ``git apply --check`` for every patch entry.
"""

import subprocess
from pathlib import Path

import pytest
from mutations.apply import ensure_worktree
from mutations.schema import MUTATIONS_ROOT, load_all, load_index

REPO = MUTATIONS_ROOT.parents[1]


def _has_commit(sha: str) -> bool:
    done = subprocess.run(  # noqa: S603
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],  # noqa: S607
        cwd=REPO, capture_output=True, check=False, timeout=60,
    )  # fmt: skip
    return done.returncode == 0


def test_every_patch_applies_at_base_sha(worktree: Path) -> None:
    base = load_index().base_sha
    if not _has_commit(base):  # a shallow CI checkout lacks history (fetch base_sha, T7.1c)
        pytest.skip(f"base_sha {base[:12]} is not in this clone (shallow checkout)")
    ensure_worktree(worktree, base)
    failed = []
    for spec in load_all():
        if spec.patch is None:
            continue
        done = subprocess.run(  # noqa: S603
            ["git", "apply", "--check", str(MUTATIONS_ROOT / spec.id / spec.patch)],  # noqa: S607
            cwd=worktree, capture_output=True, text=True, check=False, timeout=60,
        )  # fmt: skip
        if done.returncode != 0:
            failed.append(f"{spec.id}: {done.stderr.strip()[:200]}")
    assert failed == [], f"patches that do not apply at base_sha {base[:12]}: {failed}"
