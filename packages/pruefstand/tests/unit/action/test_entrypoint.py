"""``action/entrypoint.py`` with targets replayed from recordings of the real rag-demo (T1.12)."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import respx
from entrypoint import main
from testsupport.pipeline_support import BUG_URL, config_file, mini_config
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import TargetConfig


def in_process(args: Sequence[str]) -> tuple[int, str]:
    """The real CLI, called in the test process so that respx can answer the target."""
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout


class Action:
    """One invocation environment: inputs as GitHub passes them, plus the two output files."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.out = tmp_path / "out"
        self.output_file = tmp_path / "github_output"
        self.summary_file = tmp_path / "github_summary"
        self.good = config_file(tmp_path / "good.yaml", mini_config())
        target = TargetConfig(type="http", url=BUG_URL, timeout_s=5)
        self.bug = config_file(tmp_path / "bug.yaml", mini_config(target=target))
        monkeypatch.setenv("GITHUB_OUTPUT", str(self.output_file))
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(self.summary_file))

    def call(self, config: Path | str, baseline: Path | str = "", **extra: str) -> int:
        env = {
            "INPUT_CONFIG": str(config),
            "INPUT_TIER": "pr",
            "INPUT_BASELINE-RUN": str(baseline),
            "INPUT_FAIL-ON-WARN": "false",
            "INPUT_OUTPUT-DIR": str(self.out),
            "GITHUB_OUTPUT": str(self.output_file),
            "GITHUB_STEP_SUMMARY": str(self.summary_file),
            **extra,
        }
        return main(env, invoke=in_process)

    def outputs(self) -> dict[str, str]:
        text = self.output_file.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def summary(self) -> str:
        return self.summary_file.read_text(encoding="utf-8")


@pytest.fixture
def action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, router: respx.MockRouter) -> Action:
    return Action(tmp_path, monkeypatch)


def make_baseline(action: Action) -> Path:
    """A run of the good recording, made through the CLI (no gate), as the baseline-run input."""
    code, stdout = in_process(
        ["run", "--config", str(action.good), "--tier", "pr", "--out", str(action.out)]
    )
    assert code == 0, stdout
    return Path(stdout.strip().splitlines()[-1])


def test_good_run_passes(action: Action) -> None:
    baseline = make_baseline(action)
    assert action.call(action.good, baseline) == 0
    outputs = action.outputs()
    assert outputs["status"] == "pass"
    assert Path(outputs["run-dir"]).is_dir()
    assert Path(outputs["run-dir"]) != baseline
    comment = Path(outputs["comment-path"])
    assert comment.name == "comment.md"
    assert comment.read_text(encoding="utf-8").startswith("<!-- pruefstand:pr-comment -->")
    # the renderer titles a live-stack run "tier 1" (report/_context.py)
    assert "## Prüfstand tier 1: ✅ PASS" in action.summary()


def test_the_tenant_leak_recording_fails_with_exit_one(action: Action) -> None:
    baseline = make_baseline(action)
    assert action.call(action.bug, baseline) == 1
    assert action.outputs()["status"] == "fail"
    assert "FAIL" in action.summary()
    gate = json.loads((Path(action.outputs()["run-dir"]) / "gate.json").read_text("utf-8"))
    assert "tenant_leak" in {h["metric"] for h in gate["hard_fails"]}


def test_a_config_path_is_never_interpreted_by_a_shell(
    action: Action, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = '"; rm -rf /'
    assert action.call(hostile, "unused-baseline") == 2
    assert hostile in capsys.readouterr().err
    assert not action.output_file.exists()


def test_an_empty_baseline_run_is_exit_two(
    action: Action, capsys: pytest.CaptureFixture[str]
) -> None:
    assert action.call(action.good, "") == 2
    assert "baseline-run" in capsys.readouterr().err


def test_a_missing_baseline_directory_is_exit_two(action: Action, tmp_path: Path) -> None:
    assert action.call(action.good, tmp_path / "nope") == 2


INVALID = [("INPUT_TIER", "weekly"), ("INPUT_FAIL-ON-WARN", "maybe")]


@pytest.mark.parametrize(("name", "value"), INVALID)
def test_invalid_inputs_are_exit_two(action: Action, name: str, value: str) -> None:
    baseline = make_baseline(action)
    assert action.call(action.good, baseline, **{name: value}) == 2


def test_underscore_input_names_are_accepted(
    action: Action, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"INPUT_CONFIG": str(action.good), "INPUT_BASELINE_RUN": ""}
    assert main(env, invoke=in_process) == 2
    assert "baseline-run" in capsys.readouterr().err


def test_the_runs_exit_code_is_passed_through(action: Action) -> None:
    baseline = make_baseline(action)

    def failing(args: Sequence[str]) -> tuple[int, str]:
        return (3, "") if args[0] == "run" else in_process(args)

    env = {
        "INPUT_CONFIG": str(action.good),
        "INPUT_BASELINE-RUN": str(baseline),
        "INPUT_OUTPUT-DIR": str(action.out),
    }
    assert main(env, invoke=failing) == 3
    assert not action.output_file.exists()
