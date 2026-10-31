"""Hardening cases from the PR #2 review (M3 to M6): evasion forms the guard must still catch."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_text, main

SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"
HEAD_REF = "${{ github.event.pull_request.head.sha || github.sha }}"


def _job(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"runs-on": "ubuntu-24.04", "steps": [{"uses": CHECKOUT}]}
    base.update(extra)
    return base


def _wf(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": "x",
        "on": "pull_request",
        "permissions": {},
        "jobs": {"j": _job()},
    }
    doc.update(overrides)
    return doc


def _check(doc: dict[str, Any], name: str = "ci.yml") -> list[str]:
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text(name, text)


def _fails(findings: list[str], needle: str) -> bool:
    return any(needle in f for f in findings)


def _run(command: str) -> dict[str, Any]:
    return _wf(jobs={"j": _job(steps=[{"run": command}])})


@pytest.mark.parametrize(
    "expr",
    [
        "github['head_ref']",
        'github["head_ref"]',
        "GitHub.Head_Ref",
        "github.event.pull_request['title']",
        'github["event"]["pull_request"]["body"]',
        "github.event.pull_request.head.label",
        "github.event.issue.title",
        "github.event.issue.body",
        "github.event.comment.body",
        "github.event.review.body",
        "github.event.review_comment.body",
        "github.event.head_commit.message",
        "github.event.head_commit.author.email",
        "github.event.commits[0].message",
        "github.event.pages[0].page_name",
        "github.base_ref",
        "github.event.workflow_run.head_branch",
        "github.event.discussion.title",
    ],
)
def test_expression_injection_forms(expr: str) -> None:
    assert _fails(_check(_run('echo "${{ ' + expr + ' }}"')), "injection")


def test_safe_expression_in_run_passes() -> None:
    assert _check(_run('echo "${{ github.run_id }} ${{ github.sha }}"')) == []


@pytest.mark.parametrize("uses", ["Actions/Checkout", "ACTIONS/checkout"])
def test_build_images_checkout_case_insensitive(uses: str) -> None:
    doc = _wf(jobs={"b": _job(steps=[{"uses": f"{uses}@{SHA}"}])})
    assert _fails(_check(doc, "build-images.yml"), "head.sha")


def _gate_router(extra_steps: list[dict[str, Any]], **job_extra: Any) -> dict[str, Any]:
    app = {
        "uses": f"actions/create-github-app-token@{SHA}",
        "with": {
            "app-id": "${{ secrets.BOT_APP_ID }}",
            "private-key": "${{ secrets.BOT_APP_KEY }}",
        },
    }
    route = {
        "runs-on": "ubuntu-24.04",
        "environment": "gate-router",
        "permissions": {"pull-requests": "read"},
        "steps": [app, *extra_steps],
    }
    route.update(job_extra)
    return _wf(on={"pull_request_target": None}, jobs={"route": route})


def test_gate_router_baseline_passes() -> None:
    assert _check(_gate_router([{"run": "echo hi"}]), "gate-router.yml") == []


@pytest.mark.parametrize("uses", ["Actions/Checkout", "ACTIONS/CHECKOUT"])
def test_gate_router_checkout_case_insensitive(uses: str) -> None:
    doc = _gate_router([{"uses": f"{uses}@{SHA}"}])
    assert _fails(_check(doc, "gate-router.yml"), "checkout")


def test_gate_router_download_artifact_case_insensitive() -> None:
    doc = _gate_router([{"uses": f"Actions/Download-Artifact@{SHA}"}])
    assert _fails(_check(doc, "gate-router.yml"), "fetches PR code")


def test_gate_router_local_action_fails() -> None:
    assert _fails(_check(_gate_router([{"uses": "./action"}]), "gate-router.yml"), "local")


def test_gate_router_job_level_uses_fails() -> None:
    doc = _wf(
        on={"pull_request_target": None},
        jobs={"route": {"uses": f"org/repo/.github/workflows/x.yml@{SHA}"}},
    )
    assert _fails(_check(doc, "gate-router.yml"), "uses")


def test_gate_router_bracket_secret_fails() -> None:
    step = {"run": "echo", "env": {"X": "${{ secrets['OTHER'] }}"}}
    assert _fails(_check(_gate_router([step]), "gate-router.yml"), "OTHER")


def test_matrix_self_hosted_runner_fails() -> None:
    job = _job(**{"runs-on": "${{ matrix.os }}"})
    job["strategy"] = {"matrix": {"os": ["ubuntu-24.04", "self-hosted"]}}
    assert _fails(_check(_wf(jobs={"j": job})), "self-hosted")


def test_self_hosted_case_insensitive() -> None:
    doc = _wf(jobs={"j": _job(**{"runs-on": ["Self-Hosted", "a40"]})})
    assert _fails(_check(doc), "self-hosted")


@pytest.mark.parametrize("name", ["dashboard_data_pat", "Bot_Pat_X"])
def test_lowercase_pat_secret_fails(name: str) -> None:
    step = {"run": "echo", "env": {"T": "${{ secrets." + name + " }}"}}
    assert _fails(_check(_wf(jobs={"j": _job(steps=[step])})), "PAT")


@pytest.mark.parametrize(
    "ref", ["secrets['DASHBOARD_DATA_PAT']", 'secrets["bot_app_key"]', "secrets.bot_app_id"]
)
def test_secret_bracket_and_case_forms_fail(ref: str) -> None:
    step = {"run": "echo", "env": {"T": "${{ " + ref + " }}"}}
    assert _check(_wf(jobs={"j": _job(steps=[step])}))


@pytest.mark.parametrize(
    ("cron", "bad"),
    [
        ("00 2 * * *", True),
        ("0-5 2 * * *", True),
        ("0/15 2 * * *", True),
        ("*/5 2 * * *", True),
        ("5,0 2 * * *", True),
        ("13 1 * * *", False),
        ("1-5 2 * * *", False),
        ("7/15 2 * * *", False),
    ],
)
def test_cron_minute_parsing(cron: str, *, bad: bool) -> None:
    findings = _check(_wf(on={"schedule": [{"cron": cron}]}))
    assert _fails(findings, "off-minute") is bad


def test_empty_directory_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path)]) == 2
    assert "no workflows" in capsys.readouterr().err


def test_missing_directory_exits_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2
