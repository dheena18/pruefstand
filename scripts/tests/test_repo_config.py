"""Repo configuration invariants (PR #2 review M1, M2, M9, M10)."""

import re
from pathlib import Path
from typing import Any

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


def test_codeql_skips_untrusted_prs_and_scan_tolerates_the_skip() -> None:
    jobs = _load("security.yml")["jobs"]
    condition = str(jobs["codeql"]["if"])
    assert "dependabot[bot]" in condition
    assert "head.repo.full_name" in condition
    script = jobs["scan"]["steps"][0]["run"]
    assert "codeql" in script
    assert "skipped" in script
