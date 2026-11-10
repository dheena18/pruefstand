"""Structure of .github/workflows/ui.yml (T8.3: N5.5 basePath smoke, UI12-10 no try-it job)."""

from pathlib import Path
from typing import Any

import yaml
from check_workflows import check_text

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ui.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, Any] = DOC["jobs"]


def test_guard_passes() -> None:
    assert check_text("ui.yml", TEXT) == []


def test_required_check_name_is_ui_check() -> None:
    assert JOBS["check"]["name"] == "ui-check"


def test_basepath_smoke_is_part_of_the_required_check() -> None:
    assert "basepath-smoke" in JOBS["check"]["needs"]
    steps = " ".join(str(s.get("run", "")) for s in JOBS["basepath-smoke"]["steps"])
    assert "make ui-basepath" in steps


def test_every_needed_job_exists() -> None:
    assert set(JOBS["check"]["needs"]) <= set(JOBS)


def test_no_try_it_job_and_no_job_runs_the_demo_stack() -> None:
    # Try it runs only nightly on the VM (T8.4/T8.5), never in ui.yml (UI12-10).
    for name, job in JOBS.items():
        assert "try-it" not in name
        assert "try_it" not in name
        text = " ".join(str(s.get("run", "")) for s in job["steps"])
        assert "rag-demo-e2e" not in text
        assert "docker compose" not in text


def test_jobs_keep_read_only_permissions() -> None:
    assert DOC["permissions"] == {}
    for name, job in JOBS.items():
        perms = job["permissions"]
        assert perms in ({}, {"contents": "read"}), name
