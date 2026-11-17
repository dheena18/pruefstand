"""demo-ready.yml (T8.5 S6, D318): tag releases only, main code only, no secret."""

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "demo-ready.yml"
CONDITION = (
    "github.event.workflow_run.conclusion == 'success' && "
    "github.event.workflow_run.event == 'push' && "
    "startsWith(github.event.workflow_run.head_branch, 'v')"
)


def _doc() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc


def _jobs() -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = _doc()["jobs"]
    return jobs


def test_it_runs_after_release_only_and_has_no_default_permissions() -> None:
    doc = _doc()
    trigger = doc[True]  # YAML 1.1 reads the key `on` as True
    assert list(trigger) == ["workflow_run"]
    assert trigger["workflow_run"] == {"workflows": ["release"], "types": ["completed"]}
    assert doc["permissions"] == {}
    assert doc["concurrency"] == {"group": "demo-ready", "cancel-in-progress": False}


def test_every_job_marks_tag_releases_only() -> None:
    assert set(_jobs()) == {"fetch-artefacts", "pre-deploy-leak-probes", "release-demo-ready"}
    for name, job in _jobs().items():
        assert job["if"] == CONDITION, name


def test_permissions_are_exactly_the_documented_ones() -> None:
    perms = {name: job["permissions"] for name, job in _jobs().items()}
    assert perms == {
        "fetch-artefacts": {"contents": "read", "actions": "read"},
        "pre-deploy-leak-probes": {"contents": "read"},
        "release-demo-ready": {"contents": "write"},
    }


def test_the_upload_job_runs_no_repository_code() -> None:
    job = _jobs()["release-demo-ready"]
    assert job["needs"] == ["fetch-artefacts", "pre-deploy-leak-probes"]
    assert not [s for s in job["steps"] if "uses" in s]  # no checkout, no action, no image
    assert "gh release upload" in job["steps"][0]["run"]
    assert "--clobber" not in job["steps"][0]["run"]


def test_no_secret_and_the_tag_is_validated_before_use() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"secrets\.", text)
    verify = next(s for s in _jobs()["fetch-artefacts"]["steps"] if s.get("id") == "verify")
    run = verify["run"]
    assert run.index("not a release tag") < run.index("cosign verify")
    assert "release.yml@refs/tags/$TAG" in run
    assert "https://token.actions.githubusercontent.com" in run


def test_the_probe_uses_the_verified_digest_and_the_probe_project() -> None:
    job = _jobs()["pre-deploy-leak-probes"]
    assert job["env"]["DIGEST"] == "${{ needs.fetch-artefacts.outputs.digest }}"
    assert job["env"]["COMPOSE_PROJECT_NAME"] == "pruefstand-demo-probe"
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "--profile demo" in runs
    assert "cloudflared" not in runs
    assert "--no-build" in runs
    assert "check_leak_probes.py" in runs
