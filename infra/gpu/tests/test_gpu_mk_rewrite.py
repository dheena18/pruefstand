"""T3.1d CPU tests: the owner make targets refuse a ``url.<base>.insteadOf`` rewrite (D954)."""

import re
import subprocess
from pathlib import Path

import pytest
from gpu_testkit import GPU_DIR

MK = GPU_DIR.parents[1] / "mk" / "gpu.mk"


def _check_command() -> str:
    text = MK.read_text(encoding="utf-8")
    match = re.search(r"^GPU_NO_REWRITE = (.*)$", text, re.M)
    assert match, "GPU_NO_REWRITE is not defined"
    return match.group(1).replace("$$", "$")


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", "-c", _check_command()],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "GIT_CONFIG_GLOBAL": "/dev/null"},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    return tmp_path


def test_a_clean_config_passes(repo: Path) -> None:
    assert _run(repo).returncode == 0


def test_an_insteadof_rewrite_is_refused(repo: Path) -> None:
    cfg = ["git", "-C", str(repo), "config", "url.https://elsewhere.invalid/.insteadOf"]
    subprocess.run([*cfg, "https://github.com/"], check=True)  # noqa: S603
    res = _run(repo)
    assert res.returncode == 1
    assert "insteadOf" in res.stderr


@pytest.mark.parametrize("target", ["gpu-deploy-bin", "gpu-install-wrapper"])
def test_both_owner_targets_run_the_check_before_fetching(target: str) -> None:
    recipe = re.search(rf"^{target}:\n\t(.*)$", MK.read_text(encoding="utf-8"), re.M)
    assert recipe
    assert recipe.group(1).startswith("$(GPU_NO_REWRITE); git fetch")
