"""Repo configuration invariants (PR #2 review M1, M2, M9, M10)."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CONVENTIONAL_TYPES = {"chore", "build", "ci", "fix", "feat", "docs", "refactor", "test"}


def _load(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_every_dependabot_block_has_a_conventional_commit_prefix() -> None:
    doc = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert doc["updates"]
    for block in doc["updates"]:
        message = block.get("commit-message", {})
        assert message.get("prefix") in CONVENTIONAL_TYPES, block["package-ecosystem"]
        assert message.get("include") == "scope", block["package-ecosystem"]


def test_concurrency_group_includes_the_event_for_non_pr_runs() -> None:
    for name in ("ci.yml", "security.yml", "live-e2e.yml"):
        group = _load(name)["concurrency"]["group"]
        assert "github.event.pull_request.number" in group, name
        assert "github.event_name" in group, name


def test_uv_version_is_the_same_everywhere() -> None:
    versions = set()
    for name in ("ci.yml", "security.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        versions |= set(re.findall(r"^\s+version: \"([\d.]+)\"", text, flags=re.MULTILINE))
    assert len(versions) == 1, versions


def test_ci_uses_github_token_context_not_secrets() -> None:
    assert "secrets." not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_codeql_skips_dependabot_and_fork_prs() -> None:
    condition = str(_load("security.yml")["jobs"]["codeql"]["if"])
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in condition
    assert "github.actor" not in condition  # re-runs keep the PR author
    assert "head.repo.full_name == github.repository" in condition
    assert "github.event.repository.private == false" in condition


def test_dependency_review_needs_a_public_repo() -> None:
    steps = _load("security.yml")["jobs"]["zizmor"]["steps"]
    review = next(s for s in steps if "dependency-review-action" in str(s.get("uses")))
    assert "github.event.repository.private == false" in review["if"]
    assert "pull_request" in review["if"]


def _scan_exit_code(needs: dict[str, str]) -> int:
    script = str(_load("security.yml")["jobs"]["scan"]["steps"][0]["run"])
    payload = json.dumps({job: {"result": result} for job, result in needs.items()})
    done = subprocess.run(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        env={**os.environ, "NEEDS": payload},
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed")
@pytest.mark.parametrize(
    ("codeql", "other", "expected"),
    [
        ("skipped", "success", 0),
        ("success", "success", 0),
        ("failure", "success", 1),
        ("cancelled", "success", 1),
        ("success", "skipped", 1),
        ("success", "failure", 1),
    ],
)
def test_scan_aggregator_filter(codeql: str, other: str, expected: int) -> None:
    needs = {"codeql": codeql, "gitleaks": other, "pip-audit": "success", "zizmor": "success"}
    assert _scan_exit_code(needs) == expected


def test_dependabot_has_one_group_per_ecosystem_and_node_ignores() -> None:
    doc = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = [block["package-ecosystem"] for block in doc["updates"]]
    assert len(ecosystems) == len(set(ecosystems))  # one block, hence one group, per ecosystem
    for block in doc["updates"]:
        assert block["schedule"]["interval"] == "weekly"
        assert len(block["groups"]) == 1
        assert block["open-pull-requests-limit"] <= 3
    npm = next(b for b in doc["updates"] if b["package-ecosystem"] == "npm")
    ignored = {i["dependency-name"] for i in npm["ignore"]}
    assert {"@types/node", "next", "eslint-config-next"} <= ignored
