"""cassettes-models.yml (D900): least privilege, no secrets, manual trigger, budget gate."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from models.gh_models_budget import add_calls

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "cassettes-models.yml"
BUDGET = ROOT / "scripts" / "models" / "gh_models_budget.py"
DAY = "2026-11-09"
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


def test_daily_budget_is_below_the_free_tier_and_calls_are_paced_per_tier() -> None:
    assert int(DOC["env"]["DAILY_CAP"]) <= 150
    assert 60 / float(DOC["env"]["PAUSE_LOW_S"]) <= 15  # low tier, assumed 15 requests per minute
    assert 60 / float(DOC["env"]["PAUSE_HIGH_S"]) <= 10  # high tier, assumed 10 per minute
    run = str(_step("indomain_dev (")["run"])
    assert 'generate --max-calls "$left" --pause-s "$PAUSE_LOW_S"' in run
    assert 'check --max-calls "$check_left" --pause-s "$PAUSE_HIGH_S"' in run


def test_the_job_runs_on_main_only() -> None:
    assert JOB["if"] == "github.ref == 'refs/heads/main'"


def test_the_law_texts_are_downloaded_by_a_step_without_the_token() -> None:
    download = _step("Download the public law texts")
    assert "env" not in download or "PRUEFSTAND_GH_MODELS_TOKEN" not in download["env"]
    assert "data/download.py" not in str(_step("indomain_dev (")["run"])


def test_the_upload_runs_after_a_failure_too() -> None:
    upload = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"


def _env(tmp_path: Path, ledger: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "LEDGER": str(ledger),
        "DAILY_CAP": "120",
        "REQUESTED": "100",
        "START_USED": "0",
        "DAY": DAY,
        "PAUSE_LOW_S": "4.5",
        "PAUSE_HIGH_S": "6.5",
        "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
        "GITHUB_ENV": str(tmp_path / "env.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        **extra,
    }


def _bash(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = ["/bin/bash", "-c", script]  # the real steps start with `set -uo pipefail` themselves
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)  # noqa: S603


def _local(script: str) -> str:
    return script.replace("scripts/models/gh_models_budget.py", str(BUDGET)).replace(
        "uv run python", sys.executable
    )


def _ledger(path: Path, calls: int) -> Path:
    add_calls(path, DAY, calls)
    return path


STUB = """
import os
import sys
from pathlib import Path

with Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "generate":
    cache = Path("data/raw/indomain_dev_cache")
    cache.mkdir(parents=True, exist_ok=True)
    for i in range(int(os.environ["STUB_MAKE"])):
        (cache / f"g{i}.json").write_text("{}", encoding="utf-8")
raise SystemExit(1 if sys.argv[1] == "assemble" else 0)
"""


def _indomain(tmp_path: Path, used: int, make: int) -> list[str]:
    """Run the real in-domain step text with a recording stand-in for the CLI (wiring test only)."""
    stub = tmp_path / "stub_cli.py"
    stub.write_text(STUB, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    script = str(_step("indomain_dev (")["run"])
    script = script.replace(
        "uv run python -m model_selection.indomain_cli", f"{sys.executable} {stub}"
    )
    log = tmp_path / "calls.log"
    ledger = _ledger(tmp_path / "ledger.json", used)
    env = _env(tmp_path, ledger, STUB_LOG=str(log), STUB_MAKE=str(make))
    env["START_USED"] = str(used)
    run = _bash(_local(script), work, env)
    assert run.returncode == 0, run.stderr
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_the_in_domain_step_is_limited_by_the_run_and_the_day(tmp_path: Path) -> None:
    calls = _indomain(tmp_path, used=30, make=10)
    assert calls[0] == "generate --max-calls 90 --pause-s 4.5"  # min(100, 120 - 30)
    assert calls[1] == "check --max-calls 80 --pause-s 6.5"  # 90 minus the 10 new answers
    assert calls[2] == "assemble"


def test_the_in_domain_step_makes_no_call_when_the_day_is_used_up(tmp_path: Path) -> None:
    calls = _indomain(tmp_path, used=120, make=10)
    assert calls == ["assemble"]


def _skip_env(tmp_path: Path) -> dict[str, str]:
    return _env(tmp_path, _ledger(tmp_path / "ledger.json", 110))


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
    script = str(_step(name)["run"])
    assert f"need={need}" in script
    assert f"record_cassettes.sh {record_flag}" in script
    env = _skip_env(tmp_path)
    env["START_USED"] = "110"
    run = _bash(_local(script), ROOT, env)
    assert run.returncode == 0, run.stderr
    assert "skipped" in run.stdout
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").strip() == "recorded=false"


def test_a_stage_is_also_limited_by_what_earlier_stages_of_the_run_used(tmp_path: Path) -> None:
    # budget 100, the run started at 0 and has used 90 already: 10 left, below the 18 of t42
    env = _env(tmp_path, _ledger(tmp_path / "ledger.json", 90))
    script = str(_step("t42_dataset (datagen")["run"])
    run = _bash(_local(script), ROOT, env)
    assert run.returncode == 0, run.stderr
    assert "only 10 are left" in run.stdout


def test_the_header_refuses_a_zero_budget_and_an_unreadable_ledger(tmp_path: Path) -> None:
    script = _local(str(_step("Header of the job summary")["run"]))
    ledger = tmp_path / "ledger.json"
    env = _env(tmp_path, ledger, REQUESTED_INPUT="0", TARGET="indomain_dev", MATCHED="")
    assert _bash(script, ROOT, env).returncode != 0  # 0 is refused, not turned into 100
    ledger.write_text("{broken", encoding="utf-8")
    env = _env(tmp_path, ledger, REQUESTED_INPUT="50", TARGET="indomain_dev", MATCHED="")
    assert _bash(script, ROOT, env).returncode != 0  # fail closed
    env = _env(tmp_path, tmp_path / "none.json", REQUESTED_INPUT="", TARGET="all", MATCHED="")
    run = _bash(script, ROOT, env)
    assert run.returncode == 0, run.stderr
    assert "REQUESTED=100" in (tmp_path / "env.txt").read_text(encoding="utf-8")
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "SOFT counter" in summary
    assert "62 high-tier" in summary
