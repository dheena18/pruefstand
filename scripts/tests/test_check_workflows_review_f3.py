"""Review F3 / F6 / F7 (D1121): hardening rules of the workflow guard, one mutation per rule."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_text, main
from workflow_hardening import check_action_text

REPO = Path(__file__).resolve().parents[2]
SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"


def _wf(job: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    base_job: dict[str, Any] = {"runs-on": "ubuntu-24.04", "steps": [{"uses": CHECKOUT}]}
    base_job.update(job or {})
    doc: dict[str, Any] = {"name": "x", "on": "pull_request", "permissions": {}}
    doc.update(overrides)
    doc.setdefault("jobs", {"j": base_job})
    return doc


def _check(doc: dict[str, Any], name: str = "ci.yml") -> list[str]:
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text(name, text)


def _step(**step: Any) -> dict[str, Any]:
    return {"steps": [{"uses": CHECKOUT}, step]}


def test_the_baseline_workflow_passes() -> None:
    assert _check(_wf()) == []


# --- F3: string permissions --------------------------------------------------------------------


@pytest.mark.parametrize("value", ["read-all", "write-all", "read"])
def test_a_string_permission_is_refused_at_workflow_level(value: str) -> None:
    assert any("permissions" in f and value in f for f in _check(_wf(permissions=value)))


def test_read_all_is_refused_at_job_level() -> None:
    findings = _check(_wf({"permissions": "read-all"}))
    assert any("job j" in f and "read-all" in f for f in findings)


# --- F3: deny-by-default write scopes -----------------------------------------------------------

WRITE_SCOPES = [
    "packages",
    "pull-requests",
    "checks",
    "issues",
    "deployments",
    "attestations",
    "security-events",
    "discussions",
    "repository-projects",
    "actions",
]


@pytest.mark.parametrize("scope", WRITE_SCOPES)
def test_every_write_scope_needs_an_allow_list_entry(scope: str) -> None:
    findings = _check(_wf({"permissions": {scope: "write"}}))
    assert any(f"'{scope}: write' is not on the allow-list" in f for f in findings), findings


@pytest.mark.parametrize("scope", WRITE_SCOPES)
def test_a_write_scope_at_workflow_level_is_refused(scope: str) -> None:
    assert any(scope in f for f in _check(_wf(permissions={scope: "write"})))


@pytest.mark.parametrize(
    ("name", "job", "scope"),
    [
        ("live-e2e.yml", "comment", "pull-requests"),
        ("build-images.yml", "trivy", "security-events"),
    ],
)
def test_the_allow_listed_write_scopes_pass(name: str, job: str, scope: str) -> None:
    doc = _wf(jobs={job: {"runs-on": "ubuntu-24.04", "permissions": {scope: "write"}}})
    assert not any("allow-list" in f for f in _check(doc, name))


# --- F3: github.event values in run / with ------------------------------------------------------

BAD = [
    "${{ toJSON(github.event.pull_request) }}",
    "${{ toJson(github.event) }}",
    "${{ github.event.pull_request.head.repo.description }}",
    "${{ github.event.workflow_run.pull_requests[0].head.ref }}",
    "${{ github.event.workflow_run.head_repository.full_name }}",
    "${{ github.event['pull_request']['user']['login'] }}",
]
GOOD = [
    "${{ github.event.pull_request.number }}",
    "${{ github.event.number }}",
    "${{ github.event.pull_request.head.sha || github.sha }}",
    "${{ github.event.pull_request.base.sha }}",
    "${{ github.event.workflow_run.id }}",
    "${{ github.event.workflow_run.head_sha }}",
    "${{ github.event.repository.full_name }}",
    "${{ github.event_name }}",
]


@pytest.mark.parametrize("expr", BAD)
def test_an_untrusted_event_value_in_run_is_refused(expr: str) -> None:
    findings = _check(_wf(_step(run=f'echo "{expr}"')))
    assert any("github.event" in f for f in findings), findings


@pytest.mark.parametrize("expr", [*BAD, "${{ github.head_ref }}"])
def test_an_untrusted_value_in_any_with_input_is_refused(expr: str) -> None:
    step = {"uses": f"some/action@{SHA}", "with": {"text": f"x {expr}"}}
    findings = _check(_wf(_step(**step)))
    assert any("injection" in f for f in findings), findings


@pytest.mark.parametrize("expr", GOOD)
def test_the_allow_listed_event_values_pass(expr: str) -> None:
    run_doc = _wf(_step(run=f'echo "{expr}"'))
    with_doc = _wf(_step(uses=f"some/action@{SHA}", **{"with": {"ref": expr}}))
    assert _check(run_doc) == []
    assert _check(with_doc) == []


def test_a_step_output_written_to_github_env_is_refused() -> None:
    run = 'echo "X=${{ steps.meta.outputs.title }}" >> "$GITHUB_ENV"'
    findings = _check(_wf(_step(run=run)))
    assert any("GITHUB_ENV" in f for f in findings), findings


def test_a_plain_github_env_write_passes() -> None:
    assert _check(_wf(_step(run='echo "START=$(date +%s)" >> "$GITHUB_ENV"'))) == []


# --- F3: dangerous triggers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "trigger",
    ["workflow_run", "issue_comment", "pull_request_review", "pull_request_review_comment"],
)
def test_a_dangerous_trigger_needs_an_allow_list_entry(trigger: str) -> None:
    findings = _check(_wf(on={trigger: None}))
    assert any(trigger in f and "allow-list" in f for f in findings), findings


def test_the_allow_listed_docs_workflow_run_trigger_passes() -> None:
    doc = _wf(on={"workflow_run": {"workflows": ["deploy"], "types": ["completed"]}})
    assert not any("workflow_run" in f for f in _check(doc, "docs.yml"))


# --- F3: composite actions ----------------------------------------------------------------------


def _action(*steps: dict[str, Any]) -> str:
    doc = {"name": "a", "runs": {"using": "composite", "steps": list(steps)}}
    dumped = yaml.safe_dump(doc, sort_keys=False)
    return re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)


def test_a_clean_composite_action_passes() -> None:
    text = _action(
        {"uses": f"docker/setup-buildx-action@{SHA}"}, {"run": "echo ok", "shell": "bash"}
    )
    assert check_action_text("x/action.yml", text) == []


def test_an_unpinned_action_in_a_composite_action_is_refused() -> None:
    text = _action({"uses": "docker/setup-buildx-action@v3"})
    assert any("not pinned" in f for f in check_action_text("x/action.yml", text))


def test_an_untrusted_value_in_a_composite_action_is_refused() -> None:
    step = {"run": 'echo "${{ github.event.pull_request.title }}"', "shell": "bash"}
    assert any("injection" in f for f in check_action_text("x/action.yml", _action(step)))


def test_the_guard_scans_the_composite_actions_dir(tmp_path: Path) -> None:
    flows = tmp_path / "workflows"
    flows.mkdir()
    dumped = yaml.safe_dump(_wf(), sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    (flows / "ci.yml").write_text(text, encoding="utf-8")
    action = tmp_path / "actions" / "bad"
    action.mkdir(parents=True)
    (action / "action.yml").write_text(_action({"uses": "x/y@v1"}), encoding="utf-8")
    assert main([str(flows)]) == 0
    assert main([str(flows), "--actions", str(tmp_path / "actions")]) == 1


def test_the_real_workflows_and_actions_pass() -> None:
    gh = REPO / ".github"
    assert main([str(gh / "workflows"), "--actions", str(gh / "actions")]) == 0


def test_make_lint_scans_the_composite_actions() -> None:
    assert "--actions .github/actions" in (REPO / "mk" / "ci.mk").read_text(encoding="utf-8")


# --- F6 / F7 ------------------------------------------------------------------------------------


def _dependabot() -> list[dict[str, Any]]:
    doc = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    return list(doc["updates"])


def test_dependabot_covers_the_composite_actions() -> None:
    (actions,) = [u for u in _dependabot() if u["package-ecosystem"] == "github-actions"]
    assert actions.get("directories") == ["/", "/.github/actions/*"]
    assert "directory" not in actions


def test_every_dependabot_ecosystem_has_a_cooldown() -> None:
    for update in _dependabot():
        assert update.get("cooldown", {}).get("default-days") == 5, update["package-ecosystem"]


def test_cassettes_models_installs_from_the_lock_file() -> None:
    text = (REPO / ".github" / "workflows" / "cassettes-models.yml").read_text(encoding="utf-8")
    syncs = re.findall(r"uv sync[^\n]*", text)
    assert syncs
    assert all("--frozen" in s for s in syncs), syncs
