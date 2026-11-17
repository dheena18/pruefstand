"""T9.1a: guards for release-please.yml, release.yml and the release-please config (ADR-0017)."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"
PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def load(name: str) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    return doc


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps", []))


def uses(job: dict[str, Any]) -> list[str]:
    return [str(s["uses"]) for s in steps(job) if "uses" in s]


RP = load("release-please.yml")
REL = load("release.yml")
TAG_ONLY = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
RC_ONLY = "github.event_name == 'workflow_dispatch' && inputs.prerelease"
APP_TOKEN = "${{ steps.app.outputs.token }}"  # noqa: S105  (an expression, not a secret)


def test_every_action_is_pinned_by_sha() -> None:
    for doc in (RP, REL):
        for job in doc["jobs"].values():
            assert all(PIN.match(u.split(" ")[0]) for u in uses(job)), uses(job)


def test_release_please_uses_the_app_token_and_no_id_token() -> None:
    assert RP["permissions"] == {}
    job = RP["jobs"]["release-please"]
    assert job["environment"] == "release"
    assert job["permissions"] == {"contents": "read"}  # GITHUB_TOKEN never writes here
    assert "id-token" not in json.dumps(RP)
    app, rp = steps(job)[0], steps(job)[1]
    assert str(app["uses"]).startswith("actions/create-github-app-token@")
    assert rp["with"]["token"] == APP_TOKEN
    assert "GITHUB_TOKEN" not in json.dumps(job)


def test_the_lock_step_runs_after_release_please_and_commits_only_uv_lock() -> None:
    job = RP["jobs"]["release-please"]
    names = [str(s.get("name", s.get("uses", ""))) for s in steps(job)]
    lock = next(i for i, n in enumerate(names) if n.startswith("uv lock"))
    assert lock > names.index("release-please (single root package)")
    setup = next(s for s in steps(job) if str(s.get("uses", "")).startswith("astral-sh/setup-uv@"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", setup["with"]["version"])  # pinned uv
    run = str(steps(job)[lock]["run"])
    assert run.index("uv lock") < run.index("check_release_lock_diff.py") < run.index("commit")
    assert 'commit -m "chore: update uv.lock for release" -- uv.lock' in run
    assert "git add" not in run
    assert "push" not in run  # the push is its own step with the token (see below)


def test_one_root_package_and_plain_tags() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    assert list(cfg["packages"]) == ["."]
    assert cfg["include-component-in-tag"] is False
    assert cfg["release-type"] == "python"
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert list(manifest) == ["."]


def test_release_has_no_docs_deploy_and_no_pages_permission() -> None:
    assert "docs-deploy" not in REL["jobs"]
    assert "pages" not in json.dumps([j.get("permissions", {}) for j in REL["jobs"].values()])
    assert REL["permissions"] == {}


def test_id_token_only_on_publish_sign_and_attest() -> None:
    with_id = {n for n, j in REL["jobs"].items() if j.get("permissions", {}).get("id-token")}
    assert with_id == {"publish-pypi", "publish-testpypi", "sign", "attest"}
    perms = {n: j.get("permissions", {}) for n, j in REL["jobs"].items()}
    writes = {n for n, p in perms.items() if p.get("contents") == "write"}
    assert writes == {"release-assets"}


def test_images_pypi_and_signing_need_a_tag_and_rc_goes_to_testpypi_only() -> None:
    for name in ("publish-pypi", "image-action", "image-rag-demo"):
        assert REL["jobs"][name]["if"] == TAG_ONLY, name
    assert REL["jobs"]["publish-testpypi"]["if"] == RC_ONLY
    triggers = REL[True]  # YAML 1.1 reads the key `on` as True
    assert triggers["push"]["tags"] == ["v*"]
    assert triggers["workflow_dispatch"]["inputs"]["prerelease"]["type"] == "boolean"


def test_each_image_is_checked_absent_before_it_is_pushed() -> None:
    for name in ("image-action", "image-rag-demo"):
        names = [str(s.get("name", s.get("uses", ""))) for s in steps(REL["jobs"][name])]
        check = names.index("The tag must not exist yet (never overwrite)")
        assert check < names.index("Push the tag")
        assert check < names.index("Trivy gate (HIGH/CRITICAL with a fix available fails)")


def test_signing_is_by_digest_and_assets_are_never_clobbered() -> None:
    sign = str(steps(REL["jobs"]["sign"])[-1]["run"])
    assert sign.count("cosign sign --yes") == 2
    env = steps(REL["jobs"]["sign"])[-1]["env"]
    assert all("@${{ needs." in v for v in env.values())  # name@digest, never a tag
    upload = json.dumps(REL["jobs"]["release-assets"])
    assert "--clobber" not in upload
    assert "demo-ready" not in json.dumps(REL["jobs"])  # only demo-ready.yml writes that asset
    assert "image-digests.json" in upload


def test_the_app_token_is_scoped_and_only_the_push_step_sees_it() -> None:
    job = RP["jobs"]["release-please"]
    app = steps(job)[0]["with"]
    assert (app["permission-contents"], app["permission-pull-requests"]) == ("write", "write")
    lock = next(s for s in steps(job) if str(s.get("name", "")).startswith("uv lock"))
    assert "env" not in lock
    assert "token" not in json.dumps(lock).lower()
    push = next(s for s in steps(job) if s.get("name") == "Push the uv.lock commit (App token)")
    assert push["env"]["TOKEN"] == APP_TOKEN
    assert push["if"] == "steps.lock.outputs.changed == 'true'"


def test_the_scanned_image_is_the_one_pushed() -> None:
    for name in ("image-action", "image-rag-demo"):
        job_steps = steps(REL["jobs"][name])
        push = next(s for s in job_steps if s.get("name") == "Push the tag")
        assert "uses" not in push  # docker push of the loaded image, no second build
        trivy = next(s for s in job_steps if str(s.get("uses", "")).startswith("aquasecurity/"))
        assert push["env"]["IMAGE"] == trivy["with"]["image-ref"]
        assert 'docker push "$IMAGE"' in str(push["run"])


def check_step(job: str) -> dict[str, Any]:
    return next(
        s
        for s in steps(REL["jobs"][job])
        if s.get("name") == "The tag must not exist yet (never overwrite)"
    )


def fake(path: Path, name: str, rc: int, output: str) -> None:
    script = path / name
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}' >&2\nexit {rc}\n", encoding="utf-8")
    script.chmod(0o755)


PKG_OK = (0, '{"name": "x"}')
CHECK_CASES = [
    ((1, "gh: Not Found (HTTP 404)"), (1, "denied: denied"), "build"),  # first release
    ((1, "gh: Server Error (HTTP 500)"), (1, "manifest unknown"), "refuse"),  # API error
    ((1, "gh: Bad credentials (HTTP 401)"), (1, "manifest unknown"), "refuse"),
    (PKG_OK, (0, '{"schemaVersion": 2}'), "refuse"),  # the tag exists: never overwrite
    (PKG_OK, (1, "manifest unknown"), "build"),  # a definite not-found of the tag
    (PKG_OK, (1, "no such manifest: ghcr.io/x:v1"), "build"),
    (PKG_OK, (1, "denied: denied"), "refuse"),  # the package exists: denied is an error here
    (PKG_OK, (1, "unauthorized: authentication required"), "refuse"),
    (PKG_OK, (1, "received unexpected HTTP status: 503 Service Unavailable"), "refuse"),
    (PKG_OK, (1, "net/http: request canceled (Client.Timeout exceeded)"), "refuse"),
]


@pytest.mark.parametrize(("api", "registry", "verdict"), CHECK_CASES)
def test_the_tag_check_fails_closed(
    tmp_path: Path, api: tuple[int, str], registry: tuple[int, str], verdict: str
) -> None:
    fake(tmp_path, "gh", *api)
    fake(tmp_path, "docker", *registry)
    path = f"{tmp_path}{os.pathsep}{os.environ['PATH']}"
    env = {**os.environ, "PATH": path, "IMAGE": "ghcr.io/x:v1", "PACKAGE": "x", "GH_TOKEN": "t"}
    for job in ("image-action", "image-rag-demo"):
        done = subprocess.run(  # noqa: S603  (the workflow's own script)
            [shutil.which("bash") or "/bin/bash", "-e", "-c", str(check_step(job)["run"])],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
        assert (done.returncode == 0) is (verdict == "build"), (job, api, registry, done.stdout)
