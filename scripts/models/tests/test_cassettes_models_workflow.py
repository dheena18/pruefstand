"""cassettes-models.yml (D900): least privilege, no secrets, manual trigger, budget gate."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "cassettes-models.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)
JOB = DOC["jobs"]["record"]
STEPS: list[dict[str, Any]] = JOB["steps"]


def _step(prefix: str) -> dict[str, Any]:
    return next(s for s in STEPS if str(s.get("name", "")).startswith(prefix))


def test_only_a_manual_dispatch_triggers_it() -> None:
    triggers = DOC[True]  # YAML 1.1 reads the key `on` as True
    assert set(triggers) == {"workflow_dispatch"}
    options = triggers["workflow_dispatch"]["inputs"]["target"]["options"]
    assert options == ["indomain_dev", "t42_dataset", "t45_perturb", "all"]
    assert "budget_calls" in triggers["workflow_dispatch"]["inputs"]
    assert "  # schedule:" in TEXT  # the daily cron is documented, not enabled


def test_permissions_are_the_minimum() -> None:
    assert DOC["permissions"] == {}
    assert JOB["permissions"] == {"contents": "read", "models": "read"}


def test_no_secret_and_no_write_token() -> None:
    assert "secrets." not in TEXT
    assert "persist-credentials: false" in TEXT
    assert "persist-credentials: true" not in TEXT
    token_lines = [ln.strip() for ln in TEXT.splitlines() if "github.token" in ln]
    assert token_lines
    assert all(
        ln.startswith("PRUEFSTAND_GH_MODELS_TOKEN: ${{ github.token }}") for ln in token_lines
    )


def test_the_token_is_only_visible_to_the_steps_that_call_models() -> None:
    with_token = {s["name"] for s in STEPS if "PRUEFSTAND_GH_MODELS_TOKEN" in s.get("env", {})}
    assert with_token == {
        "indomain_dev (generate, spot-check, assemble)",
        "t42_dataset (datagen and support-check cassettes)",
        "t45_perturb (rewrite and equivalence-check cassettes)",
    }
    assert "PRUEFSTAND_GH_MODELS_TOKEN" not in JOB["env"]
    assert "echo $PRUEFSTAND" not in TEXT


def test_inputs_reach_the_shell_only_through_env() -> None:
    for step in STEPS:
        assert "inputs." not in str(step.get("run", "")), step["name"]


def test_nothing_is_committed_and_the_result_is_an_artefact() -> None:
    runs = "\n".join(str(s.get("run", "")) for s in STEPS)
    for forbidden in ("git commit", "git push", "gh pr "):
        assert forbidden not in runs
    upload = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["path"] == "out"


def test_every_cache_step_is_pinned_and_the_ledger_is_saved_even_after_a_failure() -> None:
    caches = [s for s in STEPS if str(s.get("uses", "")).startswith("actions/cache")]
    assert caches
    assert all("@" in s["uses"] and len(s["uses"].split("@")[1].split()[0]) == 40 for s in caches)
    assert _step("Save the daily ledger")["if"] == "always()"
    assert "always()" in _step("Save the in-domain answer cache")["if"]


def test_daily_budget_is_below_the_free_tier_and_calls_are_paced() -> None:
    assert int(DOC["env"]["DAILY_CAP"]) <= 150
    assert 60 / float(DOC["env"]["PAUSE_S"]) <= 15  # requests per minute


@pytest.mark.parametrize(
    ("name", "need", "record_flag"),
    [
        ("t42_dataset (datagen", 18, "--dataset"),
        ("t45_perturb (rewrite", 70, "--perturb"),
    ],
)
def test_a_stage_that_does_not_fit_the_daily_budget_is_skipped_without_a_call(
    tmp_path: Path, name: str, need: int, record_flag: str
) -> None:
    script = str(_step(name)["run"]).replace("uv run python", sys.executable)
    assert f"need={need}" in script
    assert f"record_cassettes.sh {record_flag}" in script
    ledger = tmp_path / "ledger.json"
    budget = ROOT / "scripts" / "models" / "gh_models_budget.py"
    subprocess.run(  # noqa: S603
        [sys.executable, str(budget), "add", "--ledger", str(ledger), "--calls", "110"],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "out.txt"
    env = {
        **os.environ,
        "LEDGER": str(ledger),
        "DAILY_CAP": "120",
        "REQUESTED": "100",
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    run = subprocess.run(  # noqa: S603
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "skipped" in run.stdout
    assert out.read_text(encoding="utf-8").strip() == "recorded=false"
