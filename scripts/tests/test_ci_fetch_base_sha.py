"""ci.yml `test` job: the base_sha fetch step is safe against a hostile index.yaml (T7.1c, D1291).

``benchmarks/mutations/index.yaml`` is PR-controlled. The step must take only the first
``base_sha:`` line, accept only 40 hex digits and end git's option parsing with ``--``, so a value
such as ``--upload-pack=...`` can never become a git option (review of #257).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STEP = "Fetch the mutation base commit"
SHA = "aac3edf14105bd83f21a417636a72dba45a889e0"


def step_script() -> str:
    """The ``run`` text of the fetch step in the ``test`` job."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    (step,) = [s for s in jobs["test"]["steps"] if str(s.get("name", "")).startswith(STEP)]
    return str(step["run"])


def run_step(tmp_path: Path, index_text: str) -> tuple[int, list[str]]:
    """Run the step with bash and a recording fake ``git``; return rc and the git argv."""
    (tmp_path / "benchmarks/mutations").mkdir(parents=True)
    (tmp_path / "benchmarks/mutations/index.yaml").write_text(index_text, encoding="utf-8")
    bin_dir, log = tmp_path / "bin", tmp_path / "git.log"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    bash = shutil.which("bash") or "/bin/bash"
    done = subprocess.run(  # noqa: S603  (the workflow's own script)
        [bash, "-e", "-c", step_script()], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False, timeout=30,
    )  # fmt: skip
    argv = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, argv


def test_the_step_validates_the_sha_and_ends_git_options() -> None:
    script = step_script()
    assert "grep -m1 -E '^base_sha:'" in script
    assert '[[ "$base" =~ ^[0-9a-f]{40}$ ]]' in script
    assert 'git fetch --no-tags --depth=1 origin -- "$base"' in script


def test_a_valid_sha_is_fetched_after_the_option_end(tmp_path: Path) -> None:
    rc, argv = run_step(tmp_path, f"base_sha: {SHA}\nentries: [N01]\n")
    assert rc == 0
    assert argv == ["fetch", "--no-tags", "--depth=1", "origin", "--", SHA]


@pytest.mark.parametrize(
    "index_text",
    [
        "base_sha: --upload-pack=touch PWNED;git-upload-pack\n",
        f"base_sha: {SHA} --upload-pack=x\n",
        "base_sha: ABCDEF0123456789ABCDEF0123456789ABCDEF01\n",
        "entries: [N01]\n",
        f"base_sha: '{SHA}'\n",
    ],
)
def test_a_hostile_or_malformed_value_never_reaches_git(tmp_path: Path, index_text: str) -> None:
    rc, argv = run_step(tmp_path, index_text)
    assert rc != 0
    assert argv == []  # git never ran


def test_only_the_first_base_sha_line_counts(tmp_path: Path) -> None:
    rc, argv = run_step(tmp_path, f"base_sha: {SHA}\nbase_sha: --upload-pack=touch PWNED\n")
    assert rc == 0
    assert argv[-2:] == ["--", SHA]
