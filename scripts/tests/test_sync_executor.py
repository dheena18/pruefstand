"""``scripts/sync_executor.sh`` (T6.2a S10, D1085): real local git repos, a stubbed ``gh``."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "sync_executor.sh"
TAG = "executor-20261115"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "test")


class Sandbox:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.public = tmp / "public"
        _init(self.public)
        for rel, text in {
            "infra/gate-executor/orchestrator/gate_orchestrator/x.py": "X = 1\n",
            "infra/gate-executor/llm-proxy/llm_proxy.py": "P = 1\n",
            "infra/gate-executor/host/job_started.sh": "#!/usr/bin/env bash\n",
            "infra/gate-executor/workflows/gate-executor.yml": "name: gate-executor\n",
            "infra/gate-executor/workflows/README.md": "source of the private workflows\n",
            "infra/gate-executor/private-repo-template/README.md": "# pruefstand-gate\n",
            "infra/gate-executor/private-repo-template/.gitignore": "*.partial\n",
            "apps/rag-demo/not_synced.py": "N = 1\n",
        }.items():
            _write(self.public, rel, text)
        _git(self.public, "add", "-A")
        _git(self.public, "commit", "-q", "-m", "public")
        self.private = tmp / "private.git"
        seed = tmp / "seed"
        _init(seed)
        _write(seed, "infra/gate-executor/orchestrator/old.py", "OLD = 1\n")
        _write(seed, "canaries/heldout/README.md", "private\n")
        _write(seed, ".github/workflows/retired.yml", "name: retired\n")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-q", "-m", "seed")
        _git(tmp, "clone", "-q", "--bare", str(seed), str(self.private))
        self.bin = tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" >> {tmp / "gh.log"}\n', encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    def tag(self, name: str = TAG, *, annotated: bool = True) -> None:
        args = ["tag", "-a", name, "-m", "executor sync"] if annotated else ["tag", name]
        _git(self.public, *args)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "PRIVATE_REMOTE": str(self.private),
            "MAIN_REF": "main",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        return subprocess.run(  # noqa: S603 - fixed argv
            ["bash", str(SCRIPT), *args], cwd=self.public, env=env, capture_output=True, text=True,  # noqa: S607 - bash from PATH
            check=False,
        )  # fmt: skip

    def private_tree(self, ref: str) -> dict[str, str]:
        names = _git(self.private, "ls-tree", "-r", "--name-only", ref).splitlines()
        return {n: _git(self.private, "show", f"{ref}:{n}") for n in names}


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_sync_copies_the_executor_dirs_at_the_tag_and_opens_a_pr(box: Sandbox) -> None:
    box.tag()
    res = box.run(TAG)
    assert res.returncode == 0, res.stderr
    tree = box.private_tree(f"sync/{TAG}")
    assert tree[".github/workflows/gate-executor.yml"] == "name: gate-executor"
    assert tree["infra/gate-executor/orchestrator/gate_orchestrator/x.py"] == "X = 1"
    assert tree["infra/gate-executor/llm-proxy/llm_proxy.py"] == "P = 1"
    assert "infra/gate-executor/host/job_started.sh" in tree
    assert "infra/gate-executor/orchestrator/old.py" not in tree  # removals propagate
    assert "infra/gate-executor/workflows/gate-executor.yml" not in tree
    assert "apps/rag-demo/not_synced.py" not in tree
    assert tree["canaries/heldout/README.md"] == "private"  # private content untouched
    commit = _git(box.public, "rev-parse", f"{TAG}^{{commit}}")
    assert tree["SYNCED_FROM"] == f"{TAG} {commit}\nworkflow gate-executor.yml"
    gh_log = (box.tmp / "gh.log").read_text(encoding="utf-8")
    assert "pr create" in gh_log
    assert "--repo dheena18/pruefstand-gate" in gh_log
    assert f"--head sync/{TAG}" in gh_log


def test_dry_run_pushes_nothing(box: Sandbox) -> None:
    box.tag()
    res = box.run(TAG, "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "infra/gate-executor/orchestrator/old.py" in res.stdout  # the removal is listed
    assert _git(box.private, "branch", "--list", f"sync/{TAG}") == ""
    assert not (box.tmp / "gh.log").exists()


@pytest.mark.parametrize("name", ["v1.2.3", "executor-2026111", "executor-20261115-x", "main"])
def test_other_tag_names_are_refused(box: Sandbox, name: str) -> None:
    if name != "main":
        box.tag(name)
    res = box.run(name)
    assert res.returncode == 2
    assert "executor-<YYYYMMDD>" in res.stderr


def test_lightweight_tag_is_refused(box: Sandbox) -> None:
    box.tag(annotated=False)
    res = box.run(TAG)
    assert res.returncode == 2
    assert "annotated" in res.stderr


def test_tag_off_main_is_refused(box: Sandbox) -> None:
    _git(box.public, "checkout", "-q", "-b", "side")
    _write(box.public, "infra/gate-executor/orchestrator/side.py", "S = 1\n")
    _git(box.public, "add", "-A")
    _git(box.public, "commit", "-q", "-m", "side")
    box.tag()
    res = box.run(TAG)
    assert res.returncode == 2
    assert "not on main" in res.stderr


def test_numbered_same_day_tag_is_accepted(box: Sandbox) -> None:
    box.tag(f"{TAG}.2")
    assert box.run(f"{TAG}.2", "--dry-run").returncode == 0


def test_the_template_lands_at_the_root_and_only_yml_reaches_the_workflows(box: Sandbox) -> None:
    box.tag()
    assert box.run(TAG).returncode == 0
    tree = box.private_tree(f"sync/{TAG}")
    assert tree["README.md"] == "# pruefstand-gate"
    assert tree[".gitignore"] == "*.partial"
    assert ".github/workflows/README.md" not in tree
    assert not any(n.startswith("infra/gate-executor/private-repo-template") for n in tree)


def _empty_remote(box: Sandbox) -> Path:
    empty = box.tmp / "empty.git"
    _git(box.tmp, "init", "-q", "--bare", "-b", "main", str(empty))
    return empty


def test_init_pushes_main_of_an_empty_private_repo_without_a_pr(box: Sandbox) -> None:
    box.private = _empty_remote(box)
    box.tag()
    res = box.run(TAG, "--init")
    assert res.returncode == 0, res.stderr
    tree = box.private_tree("main")
    assert tree["README.md"] == "# pruefstand-gate"
    assert tree[".github/workflows/gate-executor.yml"] == "name: gate-executor"
    assert tree["infra/gate-executor/llm-proxy/llm_proxy.py"] == "P = 1"
    assert tree["SYNCED_FROM"].startswith(f"{TAG} ")
    assert not (box.tmp / "gh.log").exists()


def test_init_is_refused_when_the_private_repo_has_a_branch(box: Sandbox) -> None:
    box.tag()
    res = box.run(TAG, "--init")
    assert res.returncode == 2
    assert "not empty" in res.stderr
    assert _git(box.private, "log", "--format=%s", "main") == "seed"


def test_init_dry_run_pushes_nothing(box: Sandbox) -> None:
    box.private = _empty_remote(box)
    box.tag()
    res = box.run(TAG, "--init", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert _git(box.private, "branch", "--list") == ""


def test_a_workflow_retired_in_the_public_repo_disappears_from_the_private_repo(
    box: Sandbox,
) -> None:
    box.tag()
    assert box.run(TAG).returncode == 0
    tree = box.private_tree(f"sync/{TAG}")
    assert ".github/workflows/retired.yml" not in tree  # the directory is replaced as a whole
    assert tree[".github/workflows/gate-executor.yml"] == "name: gate-executor"
    assert "workflow gate-executor.yml" in tree["SYNCED_FROM"]


def test_no_yml_in_the_source_never_wipes_the_private_workflows(box: Sandbox) -> None:
    _git(box.public, "rm", "-q", "infra/gate-executor/workflows/gate-executor.yml")
    _git(box.public, "commit", "-q", "-m", "no workflows")
    box.tag()
    res = box.run(TAG)
    assert res.returncode == 2
    assert "no *.yml or *.yaml" in res.stderr
    assert _git(box.private, "branch", "--list", f"sync/{TAG}") == ""


def test_init_with_an_unreachable_private_repo_fails(box: Sandbox) -> None:
    box.private = box.tmp / "does-not-exist.git"
    box.tag()
    res = box.run(TAG, "--init", "--dry-run")
    assert res.returncode == 1
    assert "cannot reach" in res.stderr


def test_yaml_workflows_sync_too(box: Sandbox) -> None:
    _write(box.public, "infra/gate-executor/workflows/nightly.yaml", "name: nightly\n")
    _git(box.public, "add", "-A")
    _git(box.public, "commit", "-q", "-m", "yaml workflow")
    box.tag()
    assert box.run(TAG).returncode == 0
    tree = box.private_tree(f"sync/{TAG}")
    assert tree[".github/workflows/nightly.yaml"] == "name: nightly"
    assert "workflow nightly.yaml" in tree["SYNCED_FROM"]


def test_init_names_the_remote_it_pushed_to(box: Sandbox) -> None:
    box.private = _empty_remote(box)
    box.tag()
    res = box.run(TAG, "--init")
    assert res.returncode == 0, res.stderr
    assert str(box.private) in res.stdout
    assert "dheena18/pruefstand-gate" not in res.stdout
