"""Tests for the workflow guard (T0.2 S3, S3d): fixtures are built as dicts and dumped to YAML."""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_dir, check_text, main

REPO = Path(__file__).resolve().parents[2]
SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"
APP_TOKEN = f"actions/create-github-app-token@{SHA}"
HEAD_REF = "${{ github.event.pull_request.head.sha || github.sha }}"


def _job(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "runs-on": "ubuntu-24.04",
        "permissions": {"contents": "read"},
        "steps": [{"uses": CHECKOUT}],
    }
    base.update(extra)
    return base


def _wf(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": "x",
        "on": "pull_request",
        "permissions": {},
        "jobs": {"j": _job()},
    }
    doc.update(overrides)
    return doc


def _text(doc: dict[str, Any]) -> str:
    """Dump to YAML and add the ``# vX.Y.Z`` comment every pinned ``uses:`` line must carry."""
    dumped = yaml.safe_dump(doc, sort_keys=False)
    return re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)


def _check(doc: dict[str, Any], name: str = "ci.yml") -> list[str]:
    return check_text(name, _text(doc))


def _gate_router() -> dict[str, Any]:
    steps = [
        {
            "id": "app",
            "uses": APP_TOKEN,
            "with": {
                "app-id": "${{ secrets.BOT_APP_ID }}",
                "private-key": "${{ secrets.BOT_APP_KEY }}",
            },
        },
        {"run": "echo route"},
    ]
    route = {
        "runs-on": "ubuntu-24.04",
        "environment": "gate-router",
        "permissions": {"pull-requests": "read"},
        "steps": steps,
    }
    return _wf(on={"pull_request_target": {"types": ["opened"]}}, jobs={"route": route})


def _mutated(mutate: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_gate_router())
    mutate(doc)
    return doc


def _fails(findings: list[str], needle: str) -> bool:
    return any(needle in f for f in findings)


# --- uses: pinning --------------------------------------------------------------------------


def test_unpinned_tag_fails() -> None:
    doc = _wf(jobs={"j": _job(steps=[{"uses": "actions/checkout@v4"}])})
    assert _fails(check_text("ci.yml", yaml.safe_dump(doc)), "not pinned")


def test_sha_pin_with_version_comment_passes() -> None:
    text = f"{_text(_wf())}"
    assert "# v1.2.3" in text
    assert check_text("ci.yml", text) == []


def test_sha_pin_without_version_comment_fails() -> None:
    assert _fails(check_text("ci.yml", yaml.safe_dump(_wf())), "# vX.Y.Z")


def test_local_and_docker_digest_uses_pass() -> None:
    steps = [{"uses": "./action"}, {"uses": "docker://img@sha256:" + "b" * 64}]
    assert _check(_wf(jobs={"j": _job(steps=steps)})) == []


def test_docker_uses_without_digest_fails() -> None:
    doc = _wf(jobs={"j": _job(steps=[{"uses": "docker://img:latest"}])})
    assert _fails(_check(doc), "not pinned")


def test_reusable_workflow_job_uses_must_be_pinned() -> None:
    doc = _wf(jobs={"j": {"uses": "org/repo/.github/workflows/x.yml@main"}})
    assert _fails(_check(doc), "not pinned")


# --- pull_request_target and gate-router.yml ------------------------------------------------


def test_pull_request_target_in_ci_fails() -> None:
    assert _fails(_check(_wf(on={"pull_request_target": None})), "pull_request_target")


def test_pull_request_target_in_lookalike_name_fails() -> None:
    assert _fails(_check(_gate_router(), "gate-router-2.yml"), "pull_request_target")


def test_gate_router_fixture_passes() -> None:
    assert _check(_gate_router(), "gate-router.yml") == []


def test_gate_router_with_statuses_write_fails() -> None:
    doc = _mutated(lambda d: d["jobs"]["route"]["permissions"].update(statuses="write"))
    assert _fails(_check(doc, "gate-router.yml"), "permissions")


def test_gate_router_with_contents_read_fails() -> None:
    doc = _mutated(lambda d: d["jobs"]["route"]["permissions"].update(contents="read"))
    assert _fails(_check(doc, "gate-router.yml"), "permissions")


def test_gate_router_with_checkout_fails() -> None:
    doc = _mutated(lambda d: d["jobs"]["route"]["steps"].append({"uses": CHECKOUT}))
    assert _fails(_check(doc, "gate-router.yml"), "checkout")


@pytest.mark.parametrize(
    "command",
    [
        "git fetch origin pull/1/head",
        "git clone https://github.com/x/y",
        "gh pr checkout 1",
        "gh pr diff 1 --patch | bash",
    ],
)
def test_gate_router_fetching_pr_code_fails(command: str) -> None:
    doc = _mutated(lambda d: d["jobs"]["route"]["steps"].append({"run": command}))
    assert _fails(_check(doc, "gate-router.yml"), "fetches PR code")


def test_gate_router_download_artifact_fails() -> None:
    step = {"uses": f"actions/download-artifact@{SHA}"}
    doc = _mutated(lambda d: d["jobs"]["route"]["steps"].append(step))
    assert _fails(_check(doc, "gate-router.yml"), "fetches PR code")


def test_gate_router_needs_environment() -> None:
    doc = _mutated(lambda d: d["jobs"]["route"].pop("environment"))
    assert _fails(_check(doc, "gate-router.yml"), "environment")


def test_gate_router_top_level_permissions_must_be_empty() -> None:
    doc = _mutated(lambda d: d.update(permissions={"contents": "read"}))
    assert _fails(_check(doc, "gate-router.yml"), "top-level permissions")


def test_gate_router_other_secret_fails() -> None:
    step = {"run": "echo x", "env": {"T": "${{ secrets.OTHER }}"}}
    doc = _mutated(lambda d: d["jobs"]["route"]["steps"].append(step))
    assert _fails(_check(doc, "gate-router.yml"), "secrets.OTHER")


def test_gate_router_bot_secret_outside_app_token_step_fails() -> None:
    step = {"run": "echo x", "env": {"K": "${{ secrets.BOT_APP_KEY }}"}}
    doc = _mutated(lambda d: d["jobs"]["route"]["steps"].append(step))
    assert _fails(_check(doc, "gate-router.yml"), "create-github-app-token")


@pytest.mark.parametrize("secret", ["secrets.BOT_APP_KEY", "secrets.BOT_APP_ID"])
def test_bot_secret_in_other_workflow_fails(secret: str) -> None:
    step = {"run": "echo x", "env": {"K": "${{ " + secret + " }}"}}
    assert _fails(_check(_wf(jobs={"j": _job(steps=[step])})), "gate-router.yml only")


def test_environment_gate_router_in_other_workflow_fails() -> None:
    assert _fails(_check(_wf(jobs={"j": _job(environment="gate-router")})), "gate-router.yml only")
    named = _job(environment={"name": "gate-router"})
    assert _fails(_check(_wf(jobs={"j": named})), "gate-router.yml only")


# --- build-images.yml checkout ref ----------------------------------------------------------


def _build_images(ref: str | None) -> dict[str, Any]:
    step: dict[str, Any] = {"uses": CHECKOUT}
    if ref is not None:
        step["with"] = {"ref": ref}
    return _wf(jobs={"build-image": _job(steps=[step])})


def test_build_images_head_sha_ref_passes() -> None:
    assert _check(_build_images(HEAD_REF), "build-images.yml") == []


def test_build_images_without_ref_fails() -> None:
    assert _fails(_check(_build_images(None), "build-images.yml"), "head.sha")


def test_build_images_merge_ref_fails() -> None:
    assert _fails(_check(_build_images("${{ github.sha }}"), "build-images.yml"), "head.sha")


# --- secrets, runners, crons ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["DASHBOARD_DATA_PAT", "MY_PAT_TOKEN"])
def test_pat_secret_fails(name: str) -> None:
    step = {"run": "echo x", "env": {"T": "${{ secrets." + name + " }}"}}
    assert _fails(_check(_wf(jobs={"j": _job(steps=[step])})), "PAT")


@pytest.mark.parametrize("cron", ["0 2 * * *", "*/15 * * * *", "* * * * *", "0,30 2 * * *"])
def test_busy_minute_cron_fails(cron: str) -> None:
    assert _fails(_check(_wf(on={"schedule": [{"cron": cron}]})), "off-minute")


def test_off_minute_cron_passes() -> None:
    assert _check(_wf(on={"schedule": [{"cron": "37 2 * * *"}]})) == []


def test_self_hosted_runner_fails() -> None:
    doc = _wf(jobs={"j": _job(**{"runs-on": ["self-hosted", "a40"]})})
    assert _fails(_check(doc), "self-hosted")
    assert _fails(_check(_wf(jobs={"j": _job(**{"runs-on": "self-hosted"})})), "self-hosted")


def test_missing_top_level_permissions_fails() -> None:
    doc = _wf()
    del doc["permissions"]
    assert _fails(_check(doc), "top-level permissions")


@pytest.mark.parametrize(
    "expr",
    [
        "${{ github.event.pull_request.title }}",
        "${{ github.event.pull_request.body }}",
        "${{ github.head_ref }}",
        "${{ github.event.pull_request.head.ref }}",
    ],
)
def test_expression_injection_in_run_fails(expr: str) -> None:
    step = {"run": f'echo "{expr}"'}
    assert _fails(_check(_wf(jobs={"j": _job(steps=[step])})), "injection")


def test_untrusted_value_via_env_passes() -> None:
    step = {"run": 'echo "$TITLE"', "env": {"TITLE": "${{ github.event.pull_request.title }}"}}
    assert _check(_wf(jobs={"j": _job(steps=[step])})) == []


# --- the repo itself ------------------------------------------------------------------------


def test_repo_workflows_pass() -> None:
    count, findings = check_dir(REPO / ".github" / "workflows")
    assert findings == []
    assert count >= 4


def test_main_reports_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ci.yml").write_text(_text(_wf()), encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "ok: 1 workflows checked"


def test_main_fails_with_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ci.yml").write_text(_text(_wf(on={"pull_request_target": None})), encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    assert "ci.yml" in capsys.readouterr().out


def test_unparsable_yaml_is_a_finding() -> None:
    assert _fails(check_text("ci.yml", "on: [unclosed"), "YAML")
