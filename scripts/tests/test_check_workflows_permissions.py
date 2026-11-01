"""Permission allow-list tests of the workflow guard (T0.2 S3, S3d)."""

import re
from typing import Any

import pytest
import yaml
from check_workflows import check_text

SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"
HEAD_REF = "${{ github.event.pull_request.head.sha || github.sha }}"


def _wf(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"name": "x", "on": "pull_request", "permissions": {}, "jobs": {}}
    doc.update(overrides)
    return doc


def _job(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"runs-on": "ubuntu-24.04", "steps": [{"uses": CHECKOUT}]}
    base.update(extra)
    return base


def _check(doc: dict[str, Any], name: str = "ci.yml") -> list[str]:
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text(name, text)


def _fails(findings: list[str], needle: str) -> bool:
    return any(needle in f for f in findings)


# --- permission allow-lists -----------------------------------------------------------------


def _perm(scope: str, key: str, value: str, job: str = "j") -> dict[str, Any]:
    if scope == "workflow":
        return _wf(permissions={key: value})
    steps = [{"uses": CHECKOUT, "with": {"ref": HEAD_REF}}]  # also valid for build-images.yml
    return _wf(jobs={job: _job(permissions={key: value}, steps=steps)})


ID_TOKEN_JOBS = [
    ("build-images.yml", "push-sign"),
    ("docs.yml", "deploy"),
    ("release.yml", "publish-pypi"),
    ("release.yml", "publish-testpypi"),
    ("release.yml", "sign"),
    ("release.yml", "attest"),
]


@pytest.mark.parametrize(("name", "job"), ID_TOKEN_JOBS)
def test_id_token_allowed_jobs_pass(name: str, job: str) -> None:
    assert _check(_perm("job", "id-token", "write", job), name) == []


@pytest.mark.parametrize(
    ("name", "job"),
    [
        ("docs.yml", "site"),
        ("docs.yml", "docs-build"),
        ("build-images.yml", "trivy"),
        ("release.yml", "build-dist"),
    ],
)
def test_id_token_in_another_job_of_an_allowed_file_fails(name: str, job: str) -> None:
    assert _fails(_check(_perm("job", "id-token", "write", job), name), "id-token")


@pytest.mark.parametrize("name", ["build-images.yml", "docs.yml", "release.yml"])
def test_id_token_at_workflow_level_fails_even_in_allowed_files(name: str) -> None:
    assert _fails(_check(_perm("workflow", "id-token", "write"), name), "id-token")


def test_pages_write_only_in_the_docs_deploy_job() -> None:
    assert _check(_perm("job", "pages", "write", "deploy"), "docs.yml") == []
    for name, job in [("docs.yml", "site"), ("docs.yml", "docs-build"), ("ci.yml", "deploy")]:
        assert _fails(_check(_perm("job", "pages", "write", job), name), "pages")
    assert _fails(_check(_perm("workflow", "pages", "write"), "docs.yml"), "pages")


def test_pages_read_is_not_restricted() -> None:
    assert _check(_perm("job", "pages", "read"), "ci.yml") == []


@pytest.mark.parametrize("name", ["ci.yml", "deploy.yml", "security.yml"])
def test_id_token_elsewhere_fails(name: str) -> None:
    assert _fails(_check(_perm("job", "id-token", "write"), name), "id-token")


def test_id_token_at_workflow_level_in_ci_fails() -> None:
    assert _fails(_check(_perm("workflow", "id-token", "write")), "id-token")


@pytest.mark.parametrize("name", ["live-e2e.yml", "cassettes.yml"])
def test_models_read_allowed_files_pass(name: str) -> None:
    assert _check(_perm("job", "models", "read"), name) == []


@pytest.mark.parametrize("name", ["security.yml", "action-selftest.yml", "ci.yml"])
def test_models_read_elsewhere_fails(name: str) -> None:
    assert _fails(_check(_perm("job", "models", "read"), name), "models")


@pytest.mark.parametrize("name", ["live-e2e.yml", "cassettes.yml", "ci.yml"])
def test_models_write_never_passes(name: str) -> None:
    assert _fails(_check(_perm("job", "models", "write"), name), "models")


def test_actions_read_allowlist() -> None:
    assert _check(_perm("job", "actions", "read", "fetch-artefacts"), "demo-ready.yml") == []
    assert _fails(_check(_perm("job", "actions", "read", "other"), "demo-ready.yml"), "actions")
    assert _fails(
        _check(_perm("job", "actions", "read", "fetch-artefacts"), "release.yml"), "actions"
    )
    assert _fails(_check(_perm("workflow", "actions", "read"), "demo-ready.yml"), "actions")


def test_contents_write_allowlist() -> None:
    assert _check(_perm("job", "contents", "write", "release-demo-ready"), "demo-ready.yml") == []
    assert _check(_perm("job", "contents", "write", "release-assets"), "release.yml") == []
    assert _check(_perm("job", "contents", "write", "record"), "cassettes.yml") == []
    assert _fails(
        _check(_perm("job", "contents", "write", "release-demo-ready"), "deploy.yml"), "contents"
    )
    assert _fails(
        _check(_perm("job", "contents", "write", "unlisted"), "demo-ready.yml"), "contents"
    )
    assert _fails(_check(_perm("job", "contents", "write"), "ci.yml"), "contents")


def test_statuses_write_only_in_push_sign() -> None:
    assert _check(_perm("job", "statuses", "write", "push-sign"), "build-images.yml") == []
    assert _fails(
        _check(_perm("job", "statuses", "write", "other"), "build-images.yml"), "statuses"
    )
    assert _fails(_check(_perm("job", "statuses", "write", "push-sign"), "ci.yml"), "statuses")


def test_write_all_shorthand_fails() -> None:
    assert _fails(_check(_wf(permissions="write-all")), "write-all")
