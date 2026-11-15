"""Re-review of #145 @1b636de (D1121): the remaining bypasses, one test each."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_text, main

SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"
HEAD = "${{ github.head_ref }}"
TITLE = "${{ github.event.pull_request.title }}"


def _doc(jobs: dict[str, Any], on: object = "pull_request", **top: Any) -> list[str]:
    doc = {"name": "x", "on": on, "permissions": {}, **top, "jobs": jobs}
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text("ci.yml", text)


def _job(*steps: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"runs-on": "ubuntu-24.04", "steps": [{"uses": CHECKOUT}, *steps], **extra}


def _one(*steps: dict[str, Any], **extra: Any) -> list[str]:
    return _doc({"j": _job(*steps, **extra)})


# --- 1: matrix include / exclude ---------------------------------------------------------------


@pytest.mark.parametrize("part", ["include", "exclude"])
def test_a_tainted_matrix_include_or_exclude_key_is_refused(part: str) -> None:
    strategy = {"matrix": {"os": ["a"], part: [{"t": HEAD}]}}
    found = _one({"run": 'echo "${{ matrix.t }}"'}, strategy=strategy)
    assert any("matrix.t" in f for f in found), found


def test_a_matrix_built_from_an_untrusted_expression_taints_every_key() -> None:
    strategy = {"matrix": "${{ fromJSON(github.event.pull_request.body) }}"}
    assert any("matrix.x" in f for f in _one({"run": 'echo "${{ matrix.x }}"'}, strategy=strategy))


# --- 2: the env-file rule looks at the whole run block -----------------------------------------

BLOCKS = [
    'echo "X=$T" \\\n  >> "$GITHUB_ENV"',
    'cat >> "$GITHUB_ENV" <<EOF\nX=$T\nEOF',
    'F=$GITHUB_ENV\necho "X=$T" >> "$F"',
    '{\n  echo "X=$T"\n} >> "$GITHUB_PATH"',
]


@pytest.mark.parametrize("run", BLOCKS)
def test_a_tainted_variable_anywhere_in_an_env_file_block_is_refused(run: str) -> None:
    found = _one({"run": run, "env": {"T": HEAD}})
    assert any("GITHUB_ENV/GITHUB_PATH" in f for f in found), found


@pytest.mark.parametrize("var", ["GITHUB_HEAD_REF", "GITHUB_REF_NAME", "GITHUB_EVENT_PATH"])
def test_a_runner_variable_an_attacker_controls_is_refused_in_an_env_file_block(var: str) -> None:
    found = _one({"run": f'echo "X=${var}" >> "$GITHUB_ENV"'})
    assert any("GITHUB_ENV/GITHUB_PATH" in f for f in found), found


def test_an_env_file_block_with_trusted_variables_passes() -> None:
    run = 'if [ "$FORK" = true ]; then\n  echo "MODE=skipped" >> "$GITHUB_ENV"\nfi'
    env = {"FORK": "${{ github.event.pull_request.head.repo.full_name != github.repository }}"}
    assert _one({"run": run, "env": env}) == []


# --- 3: env taint to a fixed point -------------------------------------------------------------


def test_two_hop_env_indirection_is_refused() -> None:
    job = _job({"run": 'echo "${{ env.B }}"'}, env={"B": "${{ env.A }}"})
    found = _doc({"j": job}, env={"A": TITLE})
    assert any("env.b" in f for f in found), found


def test_three_hops_through_the_step_env_are_refused() -> None:
    job = _job(
        {"run": 'echo "${{ env.C }}"', "env": {"C": "x-${{ env.B }}"}}, env={"B": "${{ env.A }}"}
    )
    assert any("env.c" in f for f in _doc({"j": job}, env={"A": HEAD}))


# --- 4: step and job outputs -------------------------------------------------------------------


def test_a_step_output_in_run_is_refused() -> None:
    writer = {"id": "x", "run": 'echo "y=$T" >> "$GITHUB_OUTPUT"', "env": {"T": HEAD}}
    found = _one(writer, {"run": 'echo "${{ steps.x.outputs.y }}"'})
    assert any("steps.x.outputs" in f for f in found), found


def test_a_job_output_in_run_is_refused() -> None:
    producer = _job(outputs={"t": TITLE})
    consumer = _job({"run": 'echo "${{ needs.a.outputs.t }}"'}, needs="a")
    found = _doc({"a": producer, "b": consumer})
    assert any("needs.a.outputs" in f for f in found), found


def test_a_step_output_in_a_github_script_is_refused() -> None:
    script = {
        "uses": f"actions/github-script@{SHA}",
        "with": {"script": 'console.log("${{ steps.x.outputs.y }}")'},
    }
    assert any("steps.x.outputs" in f for f in _one(script))


def test_a_step_output_through_env_is_the_safe_pattern() -> None:
    step = {"run": 'echo "$Y"', "env": {"Y": "${{ steps.x.outputs.y }}"}}
    assert _one(step) == []


# --- 5: more step keys and workflow_call inputs ------------------------------------------------


@pytest.mark.parametrize("key", ["shell", "working-directory"])
def test_untrusted_values_in_shell_and_working_directory_are_refused(key: str) -> None:
    step = {"run": "true", key: f"x{TITLE}"}
    assert any("injection" in f for f in _one(step)), _one(step)


def test_a_workflow_call_input_in_run_is_refused() -> None:
    on = {"workflow_call": {"inputs": {"t": {"type": "string"}}}}
    found = _doc({"j": _job({"run": 'echo "${{ inputs.t }}"'})}, on=on)
    assert any("input is interpolated" in f for f in found), found


def test_a_workflow_dispatch_input_in_run_is_not_this_rule() -> None:
    on = {"workflow_dispatch": {"inputs": {"t": {"type": "string"}}}}
    found = _doc({"j": _job({"run": 'echo "${{ inputs.t }}"'})}, on=on)
    assert not any("input is interpolated" in f for f in found)


# --- 6: computed context index -----------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    ["${{ github[format('{0}vent', 'e')].pull_request.title }}", "${{ github.event[env.K] }}"],
)
def test_a_computed_context_index_is_refused(expr: str) -> None:
    assert any("computed" in f for f in _one({"run": f'echo "{expr}"'}))


def test_a_literal_or_numeric_index_passes() -> None:
    assert _one({"run": "echo \"${{ github.event['number'] }} ${{ fromJSON('[1]')[0] }}\""}) == []


# --- 7: an --actions dir without actions -------------------------------------------------------


def test_an_actions_dir_without_any_action_fails(tmp_path: Path) -> None:
    flows = tmp_path / "workflows"
    flows.mkdir()
    (flows / "ci.yml").write_text(
        "name: x\non: push\npermissions: {}\njobs: {}\n", encoding="utf-8"
    )
    (tmp_path / "empty").mkdir()
    assert main([str(flows), "--actions", str(tmp_path / "empty")]) == 2


def test_the_real_workflows_still_pass() -> None:
    gh = Path(__file__).resolve().parents[2] / ".github"
    assert main([str(gh / "workflows"), "--actions", str(gh / "actions")]) == 0
