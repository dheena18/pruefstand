"""T6.2b S1: the push-sign job of build-images.yml (X2.4, W2.8, D107)."""

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/build-images.yml"
DOC: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
JOB: dict[str, Any] = DOC["jobs"]["push-sign"]
HEAD = "${{ github.event.pull_request.head.sha || github.sha }}"
TRIGGERS: dict[str, Any] = DOC[True]  # PyYAML reads the bare key `on` as True


def _step(prefix: str) -> dict[str, Any]:
    return next(s for s in JOB["steps"] if str(s.get("name", s.get("uses", ""))).startswith(prefix))


def test_it_triggers_on_pull_requests_main_gate_branches_and_bench_branches() -> None:
    assert "pull_request" in TRIGGERS
    assert TRIGGERS["push"]["branches"] == ["main", "gate/pr-*", "bench/**"]


def test_it_runs_for_same_repo_branches_only_and_never_for_dependabot() -> None:
    condition = str(JOB["if"])
    assert "github.event_name == 'push'" in condition
    assert "head.repo.full_name == github.repository" in condition
    assert "dependabot[bot]" in condition
    assert "needs" not in JOB  # a source-only change needs an image too


def test_permissions_are_exactly_the_four_the_job_needs() -> None:
    assert JOB["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "statuses": "write",
    }
    assert DOC["permissions"] == {}


def test_it_checks_out_and_builds_the_head_sha_never_the_merge_commit() -> None:
    checkout = next(
        s for s in JOB["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["ref"] == HEAD
    build = _step("Build and push")
    assert build["with"]["push"] is True
    assert HEAD in str(build["with"]["build-args"])
    assert build["with"]["tags"] == f"ghcr.io/dheena18/rag-demo:sha-{HEAD}"
    assert f"org.opencontainers.image.revision={HEAD}" in str(build["with"]["labels"])
    assert build["with"]["file"] == "apps/rag-demo/Dockerfile"


def test_it_signs_by_digest_and_posts_the_status_on_the_head_sha_after_signing() -> None:
    names = [str(s.get("name", s.get("uses", ""))) for s in JOB["steps"]]
    sign, status = _step("Sign the image"), _step("Post the commit status")
    assert "cosign sign --yes" in sign["run"]
    assert sign["env"]["DIGEST"] == "${{ steps.build.outputs.digest }}"
    assert "context=pruefstand/image" in status["run"]
    assert "statuses/${HEAD_SHA}" in status["run"]
    assert status["env"]["DIGEST"] == "${{ steps.build.outputs.digest }}"
    assert names.index(sign["name"]) < names.index(status["name"])
    assert JOB["env"]["HEAD_SHA"] == HEAD


def test_no_secret_other_than_the_github_token_and_the_aggregate_ignores_it() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    secrets = set(text.split("secrets.")[1:])
    assert all(s.startswith("GITHUB_TOKEN") for s in secrets)
    assert "push-sign" not in DOC["jobs"]["images-gate"]["needs"]
