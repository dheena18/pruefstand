"""``scripts/sync_executor.sh`` (T6.2a S10, D1085): real local git repos, a stubbed ``gh``."""

from pathlib import Path

import pytest
from sync_executor_testkit import TAG, Sandbox, empty_remote, git, write


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
    commit = git(box.public, "rev-parse", f"{TAG}^{{commit}}")
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
    assert git(box.private, "branch", "--list", f"sync/{TAG}") == ""
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
    git(box.public, "checkout", "-q", "-b", "side")
    write(box.public, "infra/gate-executor/orchestrator/side.py", "S = 1\n")
    git(box.public, "add", "-A")
    git(box.public, "commit", "-q", "-m", "side")
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


def test_init_pushes_main_of_an_empty_private_repo_without_a_pr(box: Sandbox) -> None:
    box.private = empty_remote(box)
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
    assert git(box.private, "log", "--format=%s", "main") == "seed"


def test_init_dry_run_pushes_nothing(box: Sandbox) -> None:
    box.private = empty_remote(box)
    box.tag()
    res = box.run(TAG, "--init", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert git(box.private, "branch", "--list") == ""


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
    git(box.public, "rm", "-q", "infra/gate-executor/workflows/gate-executor.yml")
    git(box.public, "commit", "-q", "-m", "no workflows")
    box.tag()
    res = box.run(TAG)
    assert res.returncode == 2
    assert "no *.yml or *.yaml" in res.stderr
    assert git(box.private, "branch", "--list", f"sync/{TAG}") == ""


def test_init_with_an_unreachable_private_repo_fails(box: Sandbox) -> None:
    box.private = box.tmp / "does-not-exist.git"
    box.tag()
    res = box.run(TAG, "--init", "--dry-run")
    assert res.returncode == 1
    assert "cannot reach" in res.stderr


def test_yaml_workflows_sync_too(box: Sandbox) -> None:
    write(box.public, "infra/gate-executor/workflows/nightly.yaml", "name: nightly\n")
    git(box.public, "add", "-A")
    git(box.public, "commit", "-q", "-m", "yaml workflow")
    box.tag()
    assert box.run(TAG).returncode == 0
    tree = box.private_tree(f"sync/{TAG}")
    assert tree[".github/workflows/nightly.yaml"] == "name: nightly"
    assert "workflow nightly.yaml" in tree["SYNCED_FROM"]


def test_init_names_the_remote_it_pushed_to(box: Sandbox) -> None:
    box.private = empty_remote(box)
    box.tag()
    res = box.run(TAG, "--init")
    assert res.returncode == 0, res.stderr
    assert str(box.private) in res.stdout
    assert "dheena18/pruefstand-gate" not in res.stdout
