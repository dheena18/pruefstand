"""Tests of the required-check verification of ``scripts/merge_reviewed.sh`` (stubbed ``gh``)."""

import json
import subprocess

import pytest
from merge_reviewed_testenv import REQUIRED, Env, write_json


def _ok(env: Env, verdict: str = "APPROVE") -> subprocess.CompletedProcess[str]:
    return env.run(str(env.pr_number), env.sha, verdict)


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
    (env.fake / "runjobs" / f"{200 + REQUIRED.index(name)}.json").unlink()
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
    env.patch_run("scan", **patch)  # the `scan` run, which must be security.yml
    res = _ok(env)
    assert res.returncode == 4
    assert not env.merged()


@pytest.mark.parametrize(
    "patch", [{"name": "other"}, {"head_sha": "e" * 40}, {"conclusion": "failure"}]
)
def test_forged_check_wrong_job(env: Env, patch: dict[str, object]) -> None:
    env.pr()
    path = env.fake / "runjobs" / "200.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["jobs"][0].update(patch)
    write_json(path, data)
    assert _ok(env).returncode == 4
    assert not env.merged()


def test_old_cancelled_suite_does_not_block_a_newer_green_run(env: Env) -> None:
    env.pr()
    env.add_run("check", 50, 51, "cancelled")  # older run, same name and sha
    assert _ok(env).returncode == 0


def test_old_green_suite_does_not_hide_a_newer_failure(env: Env) -> None:
    env.pr()
    env.add_run("check", 300, 301, "failure")  # newest run of ci.yml fails
    res = _ok(env)
    assert res.returncode == 4
    assert not env.merged()


def test_newest_run_still_running_is_not_green(env: Env) -> None:
    env.pr()
    env.add_run("check", 300, 301, None)
    assert _ok(env).returncode == 4


def test_run_that_does_not_list_the_pr_is_ignored(env: Env) -> None:
    env.pr()
    env.add_run("check", 300, 301, "failure", listed=False)  # another PR, same head sha
    assert _ok(env).returncode == 0
    env.patch_run("check", pull_requests=[{"number": 7, "base": {"ref": "dev"}}])
    assert _ok(env).returncode == 4  # wrong base: no run counts for this PR
    env.patch_run("check", pull_requests=[])
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
    env.patch_run("scan", event="push")  # `scan` is forged but not required here
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
