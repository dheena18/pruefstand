"""The aggregator jobs (`ci / check`, `security / scan`) must need every other job (T0.2 S1, S2)."""

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
SCHEDULE_ONLY = {"simulation-full", "hypothesis-full", "mutmut"}


def _jobs(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((REPO / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def test_ci_check_needs_every_other_job() -> None:
    jobs = _jobs("ci.yml")
    check = jobs["check"]
    assert "always()" in str(check["if"])
    assert set(check["needs"]) == set(jobs) - {"check"} - SCHEDULE_ONLY


def test_ci_has_the_interface_jobs() -> None:
    expected = {
        *("lint", "typecheck", "arch", "file-size", "test", "test-slow", "test-integration"),
        *("schemas-fresh", "commitlint", "workflow-guards", "check"),
    }
    assert expected | SCHEDULE_ONLY == set(_jobs("ci.yml"))


def test_the_unit_test_job_has_its_own_limit_of_25_minutes() -> None:
    jobs = _jobs("ci.yml")
    assert jobs["test"]["timeout-minutes"] == 25
    assert jobs["test-slow"]["timeout-minutes"] == 30
    assert [n for n, j in jobs.items() if j["timeout-minutes"] == 25] == ["test"]


def test_ci_schedule_only_jobs() -> None:
    jobs = _jobs("ci.yml")
    for name in SCHEDULE_ONLY:
        assert jobs[name]["if"] == "github.event_name == 'schedule'"
        assert "timeout-minutes" in jobs[name]
    assert jobs["simulation-full"]["timeout-minutes"] == 120
    assert jobs["hypothesis-full"]["timeout-minutes"] == 60
    assert jobs["mutmut"]["timeout-minutes"] == 300


# Per-job timeout limits of the PR jobs in minutes (D1308); unlisted jobs keep the default.
TIMEOUT_LIMITS = {"test": 25, "test-slow": 30}
DEFAULT_TIMEOUT_LIMIT = 15


def test_ci_timeouts_and_pr_jobs_skip_on_schedule() -> None:
    for name, job in _jobs("ci.yml").items():
        limit = TIMEOUT_LIMITS.get(name, DEFAULT_TIMEOUT_LIMIT)
        if name not in SCHEDULE_ONLY:
            assert job["timeout-minutes"] <= limit, name
        if name not in SCHEDULE_ONLY | {"check"}:
            assert "github.event_name != 'schedule'" in job["if"], name


def test_security_scan_needs_every_job_except_scorecard() -> None:
    jobs = _jobs("security.yml")
    scan = jobs["scan"]
    assert "always()" in str(scan["if"])
    assert set(scan["needs"]) == set(jobs) - {"scan", "scorecard"}
    assert {"codeql", "gitleaks", "pip-audit", "pnpm-audit", "zizmor", "scorecard"} <= set(jobs)


def test_skeleton_workflows() -> None:
    live = _jobs("live-e2e.yml")["live"]
    assert live["timeout-minutes"] == 30
    assert live["permissions"] == {"contents": "read", "actions": "read"}  # no models: read (D1202)
    record = _jobs("cassettes.yml")["record"]
    assert record["permissions"] == {"contents": "read"}
    assert _jobs("cassettes.yml")["push"]["permissions"] == {"contents": "write"}
