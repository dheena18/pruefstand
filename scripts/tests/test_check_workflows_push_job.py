"""The `push` job of cassettes.yml must stay free of repository code and extra permissions (N5)."""

import re
from pathlib import Path
from typing import Any

import yaml
from check_workflows import check_text

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cassettes.yml"
SHA = "b" * 40


def _doc() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _check(doc: dict[str, Any]) -> list[str]:
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text("cassettes.yml", text)


def test_the_real_workflow_passes() -> None:
    assert check_text("cassettes.yml", WORKFLOW.read_text(encoding="utf-8")) == []


def test_an_extra_permission_on_push_is_a_finding() -> None:
    doc = _doc()
    doc["jobs"]["push"]["permissions"]["pull-requests"] = "write"
    assert any("push" in f and "permissions" in f for f in _check(doc))


def test_a_repository_code_step_in_push_is_a_finding() -> None:
    doc = _doc()
    doc["jobs"]["push"]["steps"].append({"name": "x", "run": "uv run python scripts/x.py"})
    assert any("push" in f and "repository code" in f for f in _check(doc))


def test_make_python_and_scripts_are_all_findings() -> None:
    for run in ("make cassettes", "python3 -c 1", "bash scripts/models/x.sh", "./run.sh", "pytest"):
        doc = _doc()
        doc["jobs"]["push"]["steps"].append({"name": "x", "run": run})
        assert any("repository code" in f for f in _check(doc)), run


def test_an_unlisted_action_in_push_is_a_finding() -> None:
    doc = _doc()
    doc["jobs"]["push"]["steps"].append({"uses": f"astral-sh/setup-uv@{SHA}"})
    assert any("push" in f and "action" in f for f in _check(doc))
