"""Tests of ``scripts/merge_reviewed.sh`` with a stubbed ``gh`` and a real git sandbox."""

import subprocess

import pytest
from merge_reviewed_testenv import REPO, SCRIPTS, Env, git, write_json


def _ok(env: Env, verdict: str = "APPROVE") -> subprocess.CompletedProcess[str]:
    return env.run(str(env.pr_number), env.sha, verdict)


def test_happy_path_merges_pinned_and_comments_once(env: Env) -> None:
    env.pr()
    res = _ok(env, "APPROVE, no findings")
    assert res.returncode == 0, res.stderr
    calls = env.calls()
    assert f"pr merge 7 --repo {REPO} --squash --match-head-commit {env.sha}" in calls
    assert calls.count("pr comment") == 1
    assert f"merged by lead: {env.sha}; reviewer verdict: APPROVE, no findings" in calls


def test_verdict_from_environment(env: Env) -> None:
    env.pr()
    assert env.run("7", env.sha, verdict="APPROVE").returncode == 0
    assert "reviewer verdict: APPROVE" in env.calls()


def test_verdict_is_one_line_capped_and_mentions_neutralised(env: Env) -> None:
    env.pr()
    res = env.run("7", env.sha, "ok @someone and @org/team" + "x" * 400 + "\nsecond line")
    assert res.returncode == 0, res.stderr
    comment = next(ln for ln in env.calls().splitlines() if ln.startswith("pr comment"))
    assert "@" not in comment.split("--body", 1)[1]
    assert "(at)someone" in comment
    assert "second line" not in comment
    assert len(comment.split("reviewer verdict: ", 1)[1]) == 300


OWNER_CHANGES: list[dict[str, str | None]] = [
    {".github/workflows/ci.yml": "name: other\n"},
    {"docs/x.md": "x\n", ".claude/settings.json": "{ }\n"},
    {".Claude/settings.json": "{}\n"},
    {".github/workflows/new.yml": "name: n\n"},
    {"infra/vm/setup.sh": None},
    {"docs/ops/secrets.md": None},
    {"infra/vm/setup.sh": None, "docs/setup.sh": "echo vm\n"},  # rename out of an owner path
    {"docs/a.md": None, ".claude/a.md": "a\n"},  # rename into an owner path
    {"scripts/merge_reviewed.sh": "#!/bin/sh\n"},
    {"scripts/merge_paths.py": "x = 1\n"},
    {"scripts/hooks/h.py": "x = 1\n"},
    {"infra/gate-executor/a.py": "x = 1\n"},
    {"infra/cluster/a.sh": "x\n"},
    {"infra/gpu/switch-mode.sh": "x\n"},
    {".github/CODEOWNERS": "* @x\n"},
    {".github/dependabot.yml": "version: 2\n"},
    {"etc/sudoers.d/x": "x\n"},
    {"docs/../infra/vm/a": "x\n"},
]


@pytest.mark.parametrize("changes", OWNER_CHANGES)
def test_owner_paths_are_refused(env: Env, changes: dict[str, str | None]) -> None:
    env.pr(changes)
    res = _ok(env)
    assert res.returncode == 3
    assert "owner merge required" in res.stderr
    assert not env.merged()


@pytest.mark.parametrize("name", ["merge_reviewed.sh", "merge_paths.py"])
def test_modified_script_blob_is_refused(env: Env, name: str) -> None:
    env.pr()
    with (env.work / "scripts" / name).open("a", encoding="utf-8") as fh:
        fh.write("\n# local edit\n")
    res = _ok(env)
    assert res.returncode == 3
    assert "differs from origin/main" in res.stderr
    assert not env.merged()


def test_gh_under_home_is_refused(env: Env) -> None:
    env.pr()
    assert env.run("7", env.sha, "v", home=env.root).returncode == 1
    assert env.calls() == ""


def test_unknown_sha_and_head_mismatch(env: Env) -> None:
    env.pr()
    assert env.run("7", "b" * 40, "APPROVE").returncode == 5
    assert not env.merged()


@pytest.mark.parametrize(
    "field", [{"baseRefName": "dev"}, {"isDraft": True}, {"state": "CLOSED"}, {"state": "MERGED"}]
)
def test_pr_must_be_open_non_draft_on_main(env: Env, field: dict[str, object]) -> None:
    env.pr()
    env.patch("pr.json", **field)
    assert _ok(env).returncode == 5
    assert not env.merged()


def test_head_moving_before_merge_is_refused(env: Env) -> None:
    env.pr()
    write_json(
        env.fake / "pr2.json",
        {"baseRefName": "main", "state": "OPEN", "isDraft": False, "headRefOid": "c" * 40},
    )
    assert _ok(env).returncode == 5
    assert not env.merged()


def test_merge_failure_is_exit_1_without_comment(env: Env) -> None:
    env.pr()
    (env.fake / "merge_fails").write_text("", encoding="utf-8")
    assert _ok(env).returncode == 1
    assert "pr comment" not in env.calls()


@pytest.mark.parametrize("verdict", ["", "   ", "\n"])
def test_empty_verdict_is_usage_error(env: Env, verdict: str) -> None:
    env.pr()
    assert env.run("7", env.sha, verdict).returncode == 2
    assert env.run("7", env.sha).returncode == 2
    assert env.calls() == ""


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("7",),
        ("x", "a" * 40, "v"),
        ("7", "abc123", "v"),
        ("7", "A" * 40, "v"),
        ("7", "a" * 40, "v", "x"),
    ],
)
def test_usage_errors(env: Env, args: tuple[str, ...]) -> None:
    env.pr()
    assert env.run(*args, verdict="v").returncode == 2
    assert env.calls() == ""


def test_script_never_uses_admin_or_unpinned_merge() -> None:
    text = (SCRIPTS / "merge_reviewed.sh").read_text(encoding="utf-8")
    assert "--admin" not in text
    assert text.count("pr merge") == 1
    assert "--match-head-commit" in text
    assert "--squash" in text


def test_clean_filter_in_info_attributes_cannot_fake_the_script(env: Env) -> None:
    env.pr()
    original = env.root / "original.sh"
    original.write_bytes(env.script.read_bytes())
    git_dir = env.work / ".git"
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "attributes").write_text(
        "scripts/merge_reviewed.sh filter=x\n", encoding="utf-8"
    )
    git(env.work, "config", "filter.x.clean", f"cat {original}")
    with env.script.open("a", encoding="utf-8") as fh:
        fh.write("\n# local edit\n")
    res = _ok(env)
    assert res.returncode == 3
    assert "differs from origin/main" in res.stderr
    assert not env.merged()


def test_stale_or_forged_origin_main_ref_is_not_trusted(env: Env) -> None:
    env.pr()
    with env.script.open("a", encoding="utf-8") as fh:
        fh.write("\n# local edit\n")
    git(env.work, "commit", "-q", "-am", "local")
    git(env.work, "update-ref", "refs/remotes/origin/main", "HEAD")  # looks like main, is not
    res = _ok(env)
    assert res.returncode == 3
    assert not env.merged()


@pytest.mark.parametrize(
    "url", ["https://github.com/someone/pruefstand.git", "/nonexistent/elsewhere.git"]
)
def test_origin_must_be_the_public_repo(env: Env, url: str) -> None:
    env.pr()
    git(env.work, "remote", "set-url", "origin", url)
    res = _ok(env)
    assert res.returncode == 3
    assert "origin is not" in res.stderr
    assert not env.merged()
