"""Tests of ``scripts/merge_reviewed.sh`` and ``scripts/merge_paths.py`` (stubbed ``gh``).

The fake ``gh`` is a shell tool stand-in on PATH (not a model or target fake, CLAUDE.md
section 6): it answers the three read calls from fixture files and records merge and comment
calls in a log.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from merge_paths import is_owner_path, normalise, owner_paths_hit

SCRIPTS = Path(__file__).resolve().parents[1]
SCRIPT = SCRIPTS / "merge_reviewed.sh"
SHA = "a" * 40
REQUIRED = ("check", "scan", "images-gate", "docs-gate", "ui-check")

FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/calls.log"
case "$1 $2" in
  "pr view") echo "$(cat "$FAKE_DIR/head")" ;;
  "pr merge") [ -f "$FAKE_DIR/merge_fails" ] && exit 1; exit 0 ;;
  "pr comment") exit 0 ;;
  "api repos/dheena18/pruefstand/pulls/7/files") cat "$FAKE_DIR/files.jsonl" ;;
  api*) case "$2" in
      */check-runs*) cat "$FAKE_DIR/checks.tsv" ;;
      *) cat "$FAKE_DIR/files.jsonl" ;;
    esac ;;
  *) exit 9 ;;
esac
"""


def _checks(**overrides: str) -> str:
    rows = []
    for name in REQUIRED:
        conclusion = overrides.get(name, "success")
        status = "in_progress" if conclusion == "" else "completed"
        rows.append(f"{name}\t{status}\t{conclusion}\tgithub-actions")
    return "\n".join(rows) + "\n"


class Env:
    """A fake-gh sandbox for one script run."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "fake"
        self.dir.mkdir()
        gh = self.dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.set(head=SHA, files=[{"filename": "docs/a.md"}], checks=_checks())

    def set(self, *, head: str, files: list[dict[str, str]], checks: str) -> None:
        (self.dir / "head").write_text(head, encoding="utf-8")
        lines = "\n".join(json.dumps(f) for f in files) + "\n"
        (self.dir / "files.jsonl").write_text(lines, encoding="utf-8")
        (self.dir / "checks.tsv").write_text(checks, encoding="utf-8")

    def run(self, *args: str, verdict: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.dir}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.dir),
            "HOME": str(self.dir),
        }
        if verdict is not None:
            env["REVIEW_VERDICT"] = verdict
        return subprocess.run(  # noqa: S603  # fixed argv
            [str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False, timeout=60
        )

    def calls(self) -> str:
        log = self.dir / "calls.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_happy_path_merges_with_match_head_and_comments_once(env: Env) -> None:
    res = env.run("7", SHA, "APPROVE, no findings")
    assert res.returncode == 0, res.stderr
    calls = env.calls()
    assert f"pr merge 7 --repo dheena18/pruefstand --squash --match-head-commit {SHA}" in calls
    assert calls.count("pr comment") == 1
    assert f"merged by lead: {SHA}; reviewer verdict: APPROVE, no findings" in calls


def test_verdict_from_environment(env: Env) -> None:
    assert env.run("7", SHA, verdict="APPROVE").returncode == 0
    assert "reviewer verdict: APPROVE" in env.calls()


@pytest.mark.parametrize(
    "files",
    [
        [{"filename": ".github/workflows/ci.yml", "status": "modified"}],
        [{"filename": "docs/x.md"}, {"filename": ".claude/settings.json"}],
        [
            {
                "filename": "docs/new.md",
                "previous_filename": "infra/vm/setup.sh",
                "status": "renamed",
            }
        ],
        [
            {
                "filename": "infra/vm/setup.sh",
                "previous_filename": "docs/old.md",
                "status": "renamed",
            }
        ],
        [{"filename": "docs/ops/secrets.md", "status": "removed"}],
        [{"filename": "./docs/../.github/actions/x/action.yml"}],
    ],
)
def test_owner_paths_are_refused_before_checks_and_merge(
    env: Env, files: list[dict[str, str]]
) -> None:
    env.set(head=SHA, files=files, checks=_checks())
    res = env.run("7", SHA, "APPROVE")
    assert res.returncode == 3
    assert "owner merge required" in res.stderr
    assert "pr merge" not in env.calls()


def test_head_mismatch_and_unknown_sha(env: Env) -> None:
    res = env.run("7", "b" * 40, "APPROVE")
    assert res.returncode == 5
    assert "pr merge" not in env.calls()


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", ""])
@pytest.mark.parametrize("name", REQUIRED)
def test_checks_not_green(env: Env, name: str, conclusion: str) -> None:
    env.set(head=SHA, files=[{"filename": "docs/a.md"}], checks=_checks(**{name: conclusion}))
    res = env.run("7", SHA, "APPROVE")
    assert res.returncode == 4
    assert "pr merge" not in env.calls()


def test_missing_required_check_and_foreign_app(env: Env) -> None:
    rows = _checks().replace("scan\t", "scan-other\t")
    env.set(head=SHA, files=[{"filename": "docs/a.md"}], checks=rows)
    assert env.run("7", SHA, "APPROVE").returncode == 4
    forged = _checks().replace(
        "check\tcompleted\tsuccess\tgithub-actions", "check\tcompleted\tsuccess\tevil-app", 1
    )
    env.set(head=SHA, files=[{"filename": "docs/a.md"}], checks=forged)
    assert env.run("7", SHA, "APPROVE").returncode == 4


def test_merge_failure_is_exit_1_without_comment(env: Env) -> None:
    (env.dir / "merge_fails").write_text("", encoding="utf-8")
    assert env.run("7", SHA, "APPROVE").returncode == 1
    assert "pr comment" not in env.calls()


@pytest.mark.parametrize("verdict", ["", "   "])
def test_empty_verdict_is_usage_error(env: Env, verdict: str) -> None:
    assert env.run("7", SHA, verdict).returncode == 2
    assert env.run("7", SHA).returncode == 2
    assert env.calls() == ""


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("7",),
        ("x", SHA, "v"),
        ("7", "abc123", "v"),
        ("7", SHA.upper(), "v"),
        ("7", SHA, "v", "extra"),
    ],
)
def test_usage_errors(env: Env, args: tuple[str, ...]) -> None:
    assert env.run(*args, verdict="v").returncode == 2
    assert env.calls() == ""


def test_script_never_uses_admin_or_unpinned_merge() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--admin" not in text
    assert text.count("pr merge") == 1
    assert "--match-head-commit" in text
    assert "--squash" in text


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/actions/setup/action.yml",
        "infra/gpu/pruefstand-cluster",
        "infra/gpu/pruefstand-cluster/x",
        "infra/gpu/install-cluster-wrapper.sh",
        "infra/vm/vm_check.sh",
        "etc/sudoers.d/pruefstand",
        "sudoers",
        "security.yml",
        "x/security.yml",
        ".gitleaks.toml",
        "sub/.gitleaksignore",
        ".gitleaksignore",
        ".claude/settings.json",
        "docs/ops/secrets.md",
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
        ".GitHub/workflows/ci.yml",
        ".github/workflowsx/a.yml",
        ".github/pull_request_template.md",
        "infra/vm2/a",
        "infra/gpu/models.yaml",
        "docs/ops/secrets.md.bak",
        "docs/ops/lead-handoff.md",
        "Sudoers",
        "scripts/merge_reviewed.sh",
    ],
)
def test_matcher_misses(path: str) -> None:
    assert not is_owner_path(path)


def test_normalise_and_rename_semantics() -> None:
    assert normalise("a/./b/../c") == "a/c"
    assert owner_paths_hit([("docs/a.md", "docs/b.md")]) == []
    assert owner_paths_hit([("docs/a.md", ".claude/x")]) == [".claude/x"]


def _cli(script: str, stdin: str) -> int:
    argv = [sys.executable, "-I", script]
    return subprocess.run(  # noqa: S603  # fixed argv
        argv, input=stdin, capture_output=True, text=True, check=False, timeout=60
    ).returncode


def test_cli_truncated_or_bad_input() -> None:
    py = str(SCRIPTS / "merge_paths.py")
    many = "\n".join(json.dumps({"filename": f"docs/{i}.md"}) for i in range(3000))
    assert _cli(py, many) == 3
    assert _cli(py, "not json") == 64
