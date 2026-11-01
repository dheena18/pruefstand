"""Structure of .github/workflows/docs.yml (T0.4 S6: N4.5, N5.2, P5.5, UI13-07, UI13-09)."""

from pathlib import Path
from typing import Any

import yaml
from check_workflows import check_text

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docs.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, Any] = DOC["jobs"]
TRIGGERS: dict[str, Any] = DOC[True]  # PyYAML reads the bare key `on` as the boolean True


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = JOBS[job]["steps"]
    return steps


def _uses(job: str, prefix: str) -> dict[str, Any]:
    return next(s for s in _steps(job) if str(s.get("uses", "")).startswith(prefix))


def test_guard_passes() -> None:
    assert check_text("docs.yml", TEXT) == []


def test_name_and_jobs() -> None:
    assert DOC["name"] == "docs"
    assert set(JOBS) == {"docs-build", "mermaid-render", "lychee", "pydeps", "deploy", "build"}
    assert DOC["permissions"] == {}


def test_triggers_are_exactly_pull_request_push_and_workflow_run() -> None:
    assert set(TRIGGERS) == {"pull_request", "push", "workflow_run"}
    assert TRIGGERS["push"] == {"branches": ["main"]}
    assert TRIGGERS["workflow_run"] == {"workflows": ["deploy"], "types": ["completed"]}
    assert not TRIGGERS["pull_request"] or "paths" not in TRIGGERS["pull_request"]


def test_pages_and_oidc_permissions_only_on_deploy() -> None:
    assert JOBS["deploy"]["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
        "actions": "read",
    }
    for name, job in JOBS.items():
        if name != "deploy":
            assert "pages" not in job.get("permissions", {}), name
            assert "id-token" not in job.get("permissions", {}), name
            assert "actions" not in job.get("permissions", {}), name


def test_deploy_runs_only_on_a_successful_workflow_run() -> None:
    condition = str(JOBS["deploy"]["if"])
    assert "github.event_name == 'workflow_run'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert JOBS["deploy"]["environment"]["name"] == "github-pages"


def test_dashboard_site_is_downloaded_from_the_triggering_run() -> None:
    with_ = _uses("deploy", "actions/download-artifact")["with"]
    assert with_["name"] == "dashboard-site"
    assert with_["run-id"] == "${{ github.event.workflow_run.id }}"
    assert "github-token" in with_


def test_concurrency_groups() -> None:
    group = str(DOC["concurrency"]["group"])
    assert "github.event_name" in group
    assert "github.event.pull_request.number" in group
    assert "github.ref" in group
    assert DOC["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    assert JOBS["deploy"]["concurrency"] == {"group": "pages", "cancel-in-progress": False}
    assert "pages" not in group
    for name, job in JOBS.items():
        assert name == "deploy" or "concurrency" not in job, name


def test_provenance_check_comes_first_and_failure_never_deploys() -> None:
    steps = _steps("deploy")
    names = [str(s.get("name", "")) for s in steps]
    provenance = next(i for i, n in enumerate(names) if n.startswith("Provenance"))
    checkout = next(
        i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert provenance < checkout
    run = str(steps[provenance]["run"])
    for needle in (".github/workflows/deploy.yml", "main", "exit 1", "GITHUB_STEP_SUMMARY"):
        assert needle in run
    # the failure path fails the job: nothing that deploys is conditional on `failure()`/`always()`
    for step in steps:
        if str(step.get("uses", "")).startswith(
            ("actions/upload-pages-artifact", "actions/deploy-pages")
        ):
            assert "always()" not in str(step.get("if", ""))
            assert "failure()" not in str(step.get("if", ""))
    assert "continue-on-error" not in steps[provenance]


def test_checkout_uses_the_workflow_run_head_sha_without_credentials() -> None:
    with_ = _uses("deploy", "actions/checkout")["with"]
    assert with_["ref"] == "${{ github.event.workflow_run.head_sha }}"
    assert with_["persist-credentials"] is False


def test_assemble_is_called_with_the_build_id_from_head_sha_and_run_id() -> None:
    assemble = next(
        s for s in _steps("deploy") if "assemble_pages_site.sh" in str(s.get("run", ""))
    )
    expected = "${{ github.event.workflow_run.head_sha }}-${{ github.event.workflow_run.id }}"
    assert assemble["env"]["BUILD_ID"] == expected
    assert "--placeholder" in assemble["run"]


def test_upload_and_deploy_pages() -> None:
    assert _uses("deploy", "actions/upload-pages-artifact")["with"]["path"] == "_pages"
    assert "actions/deploy-pages" in str(_steps("deploy")[-1]["uses"])


def test_aggregate_needs_every_build_job_to_succeed() -> None:
    build = JOBS["build"]
    assert build["if"] == "github.event_name != 'workflow_run' && always()"
    assert set(build["needs"]) == {"docs-build", "mermaid-render", "lychee"}
    script = str(build["steps"][0]["run"])
    assert "jq -e" in script
    assert '.value.result == "success"' in script
    assert "skipped" not in script  # no build job may be skipped on the paths where `build` runs


def test_build_jobs_skip_on_workflow_run_and_pydeps_runs_on_main_only() -> None:
    for name in ("docs-build", "mermaid-render", "lychee"):
        assert JOBS[name]["if"] == "github.event_name != 'workflow_run'"
    assert "refs/heads/main" in str(JOBS["pydeps"]["if"])
    assert "push" in str(JOBS["pydeps"]["if"])


def test_every_job_has_a_timeout() -> None:
    for name, job in JOBS.items():
        assert job["timeout-minutes"] <= 20, name
