"""The security-relevant shape of the tier-1 workflows (T1.12 S6, security model of the prompt)."""

import pytest
from testsupport.workflow_checks import (
    ACTIONS,
    SCENARIOS,
    WORKFLOWS,
    Check,
    Doc,
    all_steps,
    check_baseline_lookup,
    check_cache_saves,
    check_comment_checkout,
    check_comment_jobs,
    check_marker,
    check_no_gate_status,
    check_no_judge_mode,
    check_secrets,
    check_uploads,
    load,
    read,
    steps,
    triggers,
)

# --- the real files pass ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> tuple[Doc, str]:
    text = read("live-e2e.yml")
    return load(text), text


@pytest.fixture(scope="module")
def selftest() -> tuple[Doc, str]:
    text = read("action-selftest.yml")
    return load(text), text


@pytest.mark.parametrize(
    "check",
    [
        check_comment_jobs,
        check_baseline_lookup,
        check_uploads,
        check_marker,
        check_cache_saves,
        check_no_judge_mode,
        check_no_gate_status,
        check_secrets,
        check_comment_checkout,
    ],
)
def test_live_e2e_satisfies_the_rule(check: Check, live: tuple[Doc, str]) -> None:
    assert check(*live) == []


@pytest.mark.parametrize(
    "check", [check_no_judge_mode, check_no_gate_status, check_secrets, check_comment_jobs]
)
def test_action_selftest_satisfies_the_rule(check: Check, selftest: tuple[Doc, str]) -> None:
    assert check(*selftest) == []


def test_names_and_aggregators(live: tuple[Doc, str], selftest: tuple[Doc, str]) -> None:
    assert live[0]["name"] == "live-e2e"
    assert live[0]["jobs"]["gate"]["name"] == "gate"
    assert live[0]["jobs"]["live"]["name"] == "live"  # the check name stays stable
    assert set(live[0]["jobs"]["gate"]["needs"]) >= {"prepare", "live", "scenarios"}
    assert selftest[0]["name"] == "action-selftest"
    assert selftest[0]["jobs"]["selftest"]["name"] == "selftest"


def test_triggers(live: tuple[Doc, str], selftest: tuple[Doc, str]) -> None:
    assert set(triggers(live[0])) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert triggers(live[0])["schedule"] == [{"cron": "37 2 * * *"}]
    assert set(triggers(selftest[0])) == {"pull_request", "push"}
    assert "probe_quota" in triggers(live[0])["workflow_dispatch"]["inputs"]


def test_every_workflow_starts_without_permissions(
    live: tuple[Doc, str], selftest: tuple[Doc, str]
) -> None:
    assert live[0]["permissions"] == {}
    assert selftest[0]["permissions"] == {}
    for doc in (live[0], selftest[0]):
        assert all("timeout-minutes" in job for job in doc["jobs"].values())


def test_the_live_job_budget(live: tuple[Doc, str]) -> None:
    job = live[0]["jobs"]["live"]
    assert job["timeout-minutes"] == 30
    assert job["permissions"] == {"contents": "read", "actions": "read", "models": "read"}


def test_models_read_only_in_the_allowed_files() -> None:
    allowed = {"live-e2e.yml", "cassettes.yml", "cassettes-models.yml"}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name not in allowed:
            assert "models:" not in path.read_text(encoding="utf-8"), path.name


def test_scenarios_matrix_and_when_it_runs(live: tuple[Doc, str]) -> None:
    job = live[0]["jobs"]["scenarios"]
    assert job["strategy"]["matrix"]["scenario"] == SCENARIOS
    assert job["strategy"]["fail-fast"] is False
    assert job["timeout-minutes"] == 30
    assert job["env"]["PRUEFSTAND_E2E_SCENARIO"] == "${{ matrix.scenario }}"
    plan = next(s for s in steps(live[0]["jobs"]["prepare"]) if s.get("id") == "plan")
    script = plan["run"]
    assert "schedule)" in script
    assert "workflow_dispatch)" in script
    assert "apps/rag-demo/" in plan["env"]["SCENARIO_PATHS"]
    assert job["if"] == "needs.prepare.outputs.scenarios == 'true'"


def test_pull_request_runs_never_write_the_caches(live: tuple[Doc, str]) -> None:
    saves = [s for _, s in all_steps(live[0]) if "cache/save" in str(s.get("uses", ""))]
    assert len(saves) == 2
    for path in ACTIONS.glob("*/action.yml"):
        assert "cache/save" not in path.read_text(encoding="utf-8")


def test_no_pull_request_target_and_no_self_hosted_runner() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name != "gate-router.yml":
            assert "pull_request_target" not in path.read_text(encoding="utf-8"), path.name
    for name in ("live-e2e.yml", "action-selftest.yml"):
        assert "self-hosted" not in read(name)
