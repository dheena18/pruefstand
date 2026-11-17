"""Every mutation patch applies at ``base_sha`` (T7.1a S4; follow-up T7.1c, D1290).

``apply.py`` creates its worktree at ``index.base_sha`` and applies the patch there, so a patch that
only applies to the current tree breaks the RQ3 bench (it did for N01 after D1288). This test checks
out ``base_sha`` in a temporary worktree and runs ``git apply --check`` for every patch entry.
"""

import os
import subprocess
from collections.abc import Mapping
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


def require_base(base: str, *, present: bool, env: Mapping[str, str]) -> None:
    """Fail in CI (``CI=true``: ci.yml fetches base_sha, D1291), skip in a shallow local clone."""
    if present:
        return
    msg = f"base_sha {base[:12]} is not in this clone"
    if env.get("CI") == "true":
        pytest.fail(f"{msg}: the CI test job must fetch it (ci.yml, D1291)")
    pytest.skip(f"{msg} (shallow checkout)")


def test_a_missing_base_fails_in_ci_and_skips_locally() -> None:
    require_base("a" * 40, present=True, env={"CI": "true"})  # present: nothing happens
    with pytest.raises(pytest.fail.Exception, match="must fetch it"):
        require_base("a" * 40, present=False, env={"CI": "true"})
    with pytest.raises(pytest.skip.Exception, match="shallow checkout"):
        require_base("a" * 40, present=False, env={})


def test_every_patch_applies_at_base_sha(worktree: Path) -> None:
    base = load_index().base_sha
    require_base(base, present=_has_commit(base), env=os.environ)
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
