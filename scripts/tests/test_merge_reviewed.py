"""Tests of ``scripts/merge_reviewed.sh`` with a stubbed ``gh`` and a real git sandbox."""

import json
import subprocess

import pytest
from merge_reviewed_testenv import REPO, REQUIRED, SCRIPTS, Env, write_json


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


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", None])
@pytest.mark.parametrize("name", REQUIRED)
def test_checks_not_green(env: Env, name: str, conclusion: str | None) -> None:
    env.pr()
    path = env.fake / "checkruns.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for run in data["check_runs"]:
        if run["name"] == name:
            run["conclusion"] = conclusion
            run["status"] = "completed" if conclusion else "in_progress"
    write_json(path, data)
    assert _ok(env).returncode == 4
    assert not env.merged()


def test_missing_check_and_foreign_app(env: Env) -> None:
    env.pr()
    path = env.fake / "checkruns.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["check_runs"][0]["app"]["slug"] = "evil-app"
    write_json(path, data)
    assert _ok(env).returncode == 4
    data["check_runs"][0]["app"]["slug"] = "github-actions"
    data["check_runs"].pop(1)
    write_json(path, data)
    assert _ok(env).returncode == 4
    assert not env.merged()


@pytest.mark.parametrize("name", REQUIRED)
def test_forged_check_without_a_workflow_job(env: Env, name: str) -> None:
    env.pr()
    (env.fake / "jobs" / f"{100 + REQUIRED.index(name)}.json").unlink()
    res = _ok(env)
    assert res.returncode == 4
    assert "no workflow job" in res.stderr


@pytest.mark.parametrize(
    "patch",
    [
        {"path": ".github/workflows/forged.yml"},
        {"path": ".github/workflows/ci.yml"},  # a real workflow, but not this check's
        {"event": "push"},
        {"event": "workflow_dispatch"},
        {"head_sha": "d" * 40},
        {"head_repository": {"full_name": "someone/pruefstand"}},
    ],
)
def test_forged_check_wrong_run(env: Env, patch: dict[str, object]) -> None:
    env.pr()
    env.patch("runs/201.json", **patch)  # the `scan` run, which must be security.yml
    res = _ok(env)
    assert res.returncode == 4
    assert not env.merged()


def test_forged_check_wrong_job(env: Env) -> None:
    env.pr()
    env.patch("jobs/100.json", name="other")
    assert _ok(env).returncode == 4
    env.patch("jobs/100.json", name="check", head_sha="e" * 40)
    assert _ok(env).returncode == 4


def test_ruleset_without_required_checks_is_refused(env: Env) -> None:
    env.pr()
    env.set_rules([])
    res = _ok(env)
    assert res.returncode == 4
    assert "no required checks" in res.stderr


def test_unknown_required_context_is_unverifiable(env: Env) -> None:
    env.pr()
    env.set_rules([*REQUIRED, "extra"])
    res = _ok(env)
    assert res.returncode == 4
    assert "unverifiable required context: extra" in res.stderr
    assert not env.merged()


def test_ruleset_drives_which_checks_are_verified(env: Env) -> None:
    env.pr()
    env.set_rules(["check"])
    env.patch("runs/201.json", event="push")  # `scan` is forged but not required here
    assert _ok(env).returncode == 0
    env.set_rules(["check", "scan"])
    assert _ok(env).returncode == 4


@pytest.mark.parametrize(
    ("state", "creator"),
    [
        ("failure", "pruefstand-bot[bot]"),
        ("pending", "pruefstand-bot[bot]"),
        ("success", "github-actions[bot]"),
        ("success", "someone"),
    ],
)
def test_gate_status_must_be_a_success_from_the_bot(env: Env, state: str, creator: str) -> None:
    env.pr()
    env.set_rules([*REQUIRED, "pruefstand/gate"])
    env.set_gate(state, creator)
    assert _ok(env).returncode == 4
    assert not env.merged()


def test_missing_gate_status(env: Env) -> None:
    env.pr()
    write_json(env.fake / "statuses.json", [])
    assert _ok(env).returncode == 0  # not required by the ruleset yet
    env.set_rules([*REQUIRED, "pruefstand/gate"])
    assert _ok(env).returncode == 4


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
