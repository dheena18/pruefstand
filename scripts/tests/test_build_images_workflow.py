from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/build-images.yml"


def _steps(job: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = data["jobs"][job]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], prefix: str) -> int:
    return next(i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(prefix))


def test_sarif_upload_needs_a_public_same_repo_run_and_runs_after_the_gate() -> None:
    steps = _steps("trivy")
    upload = steps[_index(steps, "Upload SARIF")]
    condition = str(upload["if"])
    assert "github.event.repository.private == false" in condition
    assert "head.repo.full_name == github.repository" in condition
    assert "always()" in condition
    assert _index(steps, "Trivy gate") < _index(steps, "Upload SARIF")


def test_trivy_gate_fails_the_job_on_findings_and_is_not_conditional() -> None:
    steps = _steps("trivy")
    gate = steps[_index(steps, "Trivy gate")]
    assert "if" not in gate
    assert gate["with"]["exit-code"] == "1"
    assert gate["with"]["severity"] == "HIGH,CRITICAL"
    assert gate["with"]["ignore-unfixed"] is True


def test_aggregate_accepts_skipped_but_not_failed() -> None:
    script = str(_steps("images-gate")[0]["run"])
    assert "success|skipped" in script
    assert "exit 1" in script


def test_sarif_upload_is_skipped_for_dependabot() -> None:
    steps = _steps("trivy")
    assert "github.actor != 'dependabot[bot]'" in str(steps[_index(steps, "Upload SARIF")]["if"])


def test_change_detection_covers_the_root_pyproject() -> None:
    script = WORKFLOW.read_text(encoding="utf-8")
    assert "^pyproject\\.toml$" in script


REQUIRED_CHECK_NAMES = ("check", "scan", "images-gate", "docs-gate")


def test_required_check_job_names_are_unique_across_all_workflows() -> None:
    """A required check is matched by job name, so each name may appear on exactly one job."""
    seen: dict[str, list[str]] = {name: [] for name in REQUIRED_CHECK_NAMES}
    for path in sorted(WORKFLOW.parent.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in data.get("jobs", {}).items():
            display = str(job.get("name", job_id))
            if display in seen:
                seen[display].append(f"{path.name}:{job_id}")
    assert {k: len(v) for k, v in seen.items()} == dict.fromkeys(REQUIRED_CHECK_NAMES, 1), seen


def test_aggregator_job_ids_and_names() -> None:
    images = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["images-gate"]
    assert images["name"] == "images-gate"
    docs = yaml.safe_load((WORKFLOW.parent / "docs.yml").read_text(encoding="utf-8"))
    assert docs["jobs"]["docs-gate"]["name"] == "docs-gate"
