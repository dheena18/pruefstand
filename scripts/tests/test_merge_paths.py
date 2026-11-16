"""Tests of the owner-path matcher ``scripts/merge_paths.py``."""

import subprocess
import sys

import pytest
from merge_paths import MAX_FILES, is_owner_path, normalise, owner_paths_hit
from merge_reviewed_testenv import SCRIPTS


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/actions/setup/action.yml",
        ".GitHub/Workflows/ci.yml",
        "infra/gpu/pruefstand-cluster",
        "infra/gpu/pruefstand-cluster/x",
        "infra/gpu/install-cluster-wrapper.sh",
        "infra/gpu/a.sh",
        "infra/vm/vm_check.sh",
        "infra/cluster/x",
        "infra/gate-executor/orchestrator/a.py",
        "etc/sudoers.d/pruefstand",
        "Sudoers",
        "security.yml",
        "x/Security.yml",
        ".gitleaks.toml",
        "sub/.gitleaksignore",
        ".claude/settings.json",
        ".Claude/settings.json",
        "docs/ops/secrets.md",
        "Docs/Ops/Secrets.md",
        ".github/CODEOWNERS",
        "docs/CODEOWNERS",
        "apps/x/codeowners",
        ".github/dependabot.yml",
        "scripts/merge_reviewed.sh",
        "scripts/merge_paths.py",
        "scripts/hooks/format_edited.py",
        "scripts/lead/draft_push.sh",
        "scripts/lead/tests/test_drafts.py",
        "Scripts/Lead/lib.sh",
        "./infra/vm/a",
        "/infra/vm/a",
        "docs/../infra/vm/a",
        "infra//vm/a",
        "../outside",
        "",
    ],
)
def test_matcher_hits(path: str) -> None:
    assert is_owner_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/a.md",
        ".github/workflowsx/a.yml",
        ".github/pull_request_template.md",
        "infra/vm2/a",
        "infra/gpu/models.yaml",
        "docs/ops/secrets.md.bak",
        "docs/ops/lead-handoff.md",
        "scripts/merge_reviewed_notes.md",
        "scripts/leadership.md",
    ],
)
def test_matcher_misses(path: str) -> None:
    assert not is_owner_path(path)


def test_normalise_and_pairs() -> None:
    assert normalise("a/./b/../c") == "a/c"
    assert owner_paths_hit(["docs/a.md", "docs/b.md"]) == []
    assert owner_paths_hit(["docs/a.md", ".claude/x"]) == [".claude/x"]


def _cli(stdin: bytes) -> int:
    script = str(SCRIPTS / "merge_paths.py")
    return subprocess.run(  # noqa: S603  # fixed argv
        [sys.executable, "-I", script], input=stdin, capture_output=True, check=False, timeout=60
    ).returncode


def _nul(count: int) -> bytes:
    return b"".join(f"docs/{i}.md\0".encode() for i in range(count))


def test_cli_file_count_limit_and_bad_input() -> None:
    assert MAX_FILES == 3000
    assert _cli(_nul(2999)) == 0
    assert _cli(_nul(3000)) == 3
    assert _cli(b"") == 3
    assert _cli(b"docs/a.md\0.claude/x\0") == 3
    assert _cli(b"\xff\xfe") == 64
