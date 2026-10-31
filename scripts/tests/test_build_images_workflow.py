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
    script = str(_steps("build")[0]["run"])
    assert "success|skipped" in script
    assert "exit 1" in script
