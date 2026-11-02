"""Structure of .github/workflows/docs.yml (T0.4 S6: N4.5, N5.2, P5.5, UI13-07, UI13-09)."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_text

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docs.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, Any] = DOC["jobs"]
TRIGGERS: dict[str, Any] = DOC[True]  # PyYAML reads the bare key `on` as the boolean True
REPO = "dheena18/pruefstand"


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = JOBS[job]["steps"]
    return steps


def _uses(job: str, prefix: str) -> dict[str, Any]:
    return next(s for s in _steps(job) if str(s.get("uses", "")).startswith(prefix))


def _named(job: str, prefix: str) -> dict[str, Any]:
    return next(s for s in _steps(job) if str(s.get("name", "")).startswith(prefix))


def test_guard_passes() -> None:
    assert check_text("docs.yml", TEXT) == []


def test_name_and_jobs() -> None:
    assert DOC["name"] == "docs"
    assert set(JOBS) == {
        "docs-build",
        "mermaid-render",
        "lychee",
        "pydeps",
        "site",
        "deploy",
        "docs-gate",
    }
    assert DOC["permissions"] == {}


def test_triggers_are_exactly_pull_request_push_and_workflow_run() -> None:
    assert set(TRIGGERS) == {"pull_request", "push", "workflow_run"}
    assert TRIGGERS["push"] == {"branches": ["main"]}
    assert TRIGGERS["workflow_run"] == {"workflows": ["deploy"], "types": ["completed"]}
    assert not TRIGGERS["pull_request"] or "paths" not in TRIGGERS["pull_request"]


def test_site_job_has_read_permissions_only() -> None:
    assert JOBS["site"]["permissions"] == {"contents": "read", "actions": "read"}


def test_deploy_job_holds_only_the_pages_permissions() -> None:
    assert JOBS["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert JOBS["deploy"]["needs"] == "site"
    assert JOBS["deploy"]["environment"]["name"] == "github-pages"
    assert JOBS["deploy"]["concurrency"] == {"group": "pages", "cancel-in-progress": False}
    steps = _steps("deploy")
    assert len(steps) == 1
    assert str(steps[0]["uses"]).startswith("actions/deploy-pages@")


def test_pages_oidc_and_actions_permissions_only_where_needed() -> None:
    for name, job in JOBS.items():
        perms = job.get("permissions", {})
        if name != "deploy":
            assert "pages" not in perms, name
            assert "id-token" not in perms, name
        if name != "site":
            assert "actions" not in perms, name


@pytest.mark.parametrize("job", ["site", "deploy"])
def test_site_and_deploy_run_only_on_a_successful_workflow_run_of_a_public_repo(job: str) -> None:
    condition = str(JOBS[job]["if"])
    assert "github.event_name == 'workflow_run'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.repository.private == false" in condition


def test_dashboard_site_is_downloaded_from_the_triggering_run() -> None:
    with_ = _uses("site", "actions/download-artifact")["with"]
    assert with_["name"] == "dashboard-site"
    assert with_["run-id"] == "${{ github.event.workflow_run.id }}"
    assert "github-token" in with_


def test_artifact_lookup_is_paginated_and_filtered_by_name() -> None:
    run = str(_named("site", "Find the dashboard-site")["run"])
    assert "--paginate" in run
    assert "name=dashboard-site" in run
    assert "per_page=100" in run


def test_concurrency_groups() -> None:
    group = str(DOC["concurrency"]["group"])
    assert "github.event_name" in group
    assert "github.event.pull_request.number" in group
    assert "github.ref" in group
    assert DOC["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    assert "pages" not in group
    for name, job in JOBS.items():
        assert name == "deploy" or "concurrency" not in job, name


def test_provenance_check_comes_first_and_failure_never_deploys() -> None:
    steps = _steps("site")
    names = [str(s.get("name", "")) for s in steps]
    provenance = next(i for i, n in enumerate(names) if n.startswith("Provenance"))
    checkout = next(
        i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert provenance == 0 < checkout
    run = str(steps[provenance]["run"])
    assert '[ "$reason" != ok ]' in run  # an empty answer is a failure, only "ok" passes
    for needle in (".github/workflows/deploy.yml", "main", "exit 1", "GITHUB_STEP_SUMMARY"):
        assert needle in run
    # the failure path fails the job: nothing that deploys is conditional on `failure()`/`always()`
    for job in ("site", "deploy"):
        for step in _steps(job):
            assert "always()" not in str(step.get("if", ""))
            assert "failure()" not in str(step.get("if", ""))
    assert "continue-on-error" not in steps[provenance]
    assert "always()" not in str(JOBS["deploy"]["if"])


def _provenance_filter() -> str:
    run = str(_named("site", "Provenance")["run"])
    found = re.search(r"--arg repo \"\$GITHUB_REPOSITORY\" '(.*?)'\)", run, re.DOTALL)
    assert found is not None
    return found.group(1)


def _run(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "path": ".github/workflows/deploy.yml",
        "head_branch": "main",
        "event": "push",
        "conclusion": "success",
        "head_repository": {"full_name": REPO},
    }
    base.update(over)
    return base


PROVENANCE_CASES = [
    ("empty response body", None, False),
    ("object without fields", {}, False),
    ("same-repo push on main", _run(), True),
    ("schedule on main", _run(event="schedule"), True),
    ("workflow_dispatch on main", _run(event="workflow_dispatch"), True),
    ("workflow_run event", _run(event="workflow_run"), False),
    ("same-repo pull_request", _run(event="pull_request", head_branch="feat/x"), False),
    (
        "fork pull_request",
        _run(event="pull_request", head_repository={"full_name": "evil/pruefstand"}),
        False,
    ),
    ("null head_repository", _run(head_repository=None), False),
    ("push on another branch", _run(head_branch="feat/x"), False),
    ("another workflow file", _run(path=".github/workflows/ci.yml"), False),
    ("failed run", _run(conclusion="failure"), False),
]


@pytest.mark.parametrize(("label", "run", "accepted"), PROVENANCE_CASES)
def test_provenance_filter_accepts_and_rejects(
    label: str, run: dict[str, Any] | None, *, accepted: bool
) -> None:
    jq = shutil.which("jq")
    assert jq is not None
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [jq, "-r", "--arg", "repo", REPO, _provenance_filter()],
        input="" if run is None else json.dumps(run),
        capture_output=True,
        text=True,
        check=True,
    )
    assert (result.stdout.strip() == "ok") is accepted, label


def test_checkout_uses_the_workflow_run_head_sha_without_credentials() -> None:
    with_ = _uses("site", "actions/checkout")["with"]
    assert with_["ref"] == "${{ github.event.workflow_run.head_sha }}"
    assert with_["persist-credentials"] is False


def test_assemble_is_called_with_the_build_id_from_head_sha_and_run_id() -> None:
    assemble = next(s for s in _steps("site") if "assemble_pages_site.sh" in str(s.get("run", "")))
    expected = "${{ github.event.workflow_run.head_sha }}-${{ github.event.workflow_run.id }}"
    assert assemble["env"]["BUILD_ID"] == expected
    assert "--placeholder" in assemble["run"]


def test_site_job_uploads_the_pages_artifact() -> None:
    assert _uses("site", "actions/upload-pages-artifact")["with"]["path"] == "_pages"
    assert not any("upload-pages-artifact" in str(s.get("uses", "")) for s in _steps("deploy"))


def test_aggregate_needs_every_build_job_to_succeed() -> None:
    build = JOBS["docs-gate"]
    assert build["if"] == "github.event_name != 'workflow_run' && always()"
    assert set(build["needs"]) == {"docs-build", "mermaid-render", "lychee"}
    script = str(build["steps"][0]["run"])
    assert "jq -e" in script
    assert '.value.result == "success"' in script
    assert "skipped" not in script  # no build job may be skipped on the paths where `docs-gate` runs


def test_build_jobs_skip_on_workflow_run_and_pydeps_runs_on_main_only() -> None:
    for name in ("docs-build", "mermaid-render", "lychee"):
        assert JOBS[name]["if"] == "github.event_name != 'workflow_run'"
    assert "refs/heads/main" in str(JOBS["pydeps"]["if"])
    assert "push" in str(JOBS["pydeps"]["if"])


def test_every_job_has_a_timeout() -> None:
    for name, job in JOBS.items():
        assert job["timeout-minutes"] <= 20, name
