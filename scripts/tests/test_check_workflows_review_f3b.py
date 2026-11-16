"""Re-review of #145 (D1121): bare github context, env/matrix indirection, env-file writes."""

import re
from typing import Any

import pytest
import yaml
from check_workflows import check_text, main

SHA = "a" * 40
CHECKOUT = f"actions/checkout@{SHA}"
TITLE = "${{ github.event.pull_request.title }}"


def _check(job: dict[str, Any], on: object = "pull_request") -> list[str]:
    base: dict[str, Any] = {"runs-on": "ubuntu-24.04", "steps": [{"uses": CHECKOUT}]}
    base.update(job)
    doc = {"name": "x", "on": on, "permissions": {}, "jobs": {"j": base}}
    dumped = yaml.safe_dump(doc, sort_keys=False)
    text = re.sub(r"(uses: \S+@[0-9a-f]{40})$", r"\1 # v1.2.3", dumped, flags=re.MULTILINE)
    return check_text("ci.yml", text)


def _run(run: str, **step: Any) -> dict[str, Any]:
    return {"steps": [{"uses": CHECKOUT}, {"run": run, **step}]}


@pytest.mark.parametrize("expr", ["${{ toJSON(github) }}", "${{ github }}"])
def test_the_whole_github_context_is_refused(expr: str) -> None:
    assert any("injection" in f for f in _check(_run(f"echo '{expr}'")))


def test_a_string_literal_named_github_passes() -> None:
    assert _check(_run("echo \"${{ inputs.m || 'github/openai/gpt' }}\"")) == []


def test_an_untrusted_value_through_env_is_refused() -> None:
    step = _run('echo "${{ env.T }}"', env={"T": TITLE})
    assert any("env.t" in f for f in _check(step))
    assert any("env.t" in f for f in _check({**_run('echo "${{ env.T }}"'), "env": {"T": TITLE}}))


def test_the_env_var_itself_is_the_safe_pattern() -> None:
    assert _check(_run('echo "$T"', env={"T": TITLE})) == []


def test_an_untrusted_value_through_the_matrix_is_refused() -> None:
    job = {**_run('echo "${{ matrix.t }}"'), "strategy": {"matrix": {"t": [TITLE]}}}
    assert any("matrix.t" in f for f in _check(job))


@pytest.mark.parametrize(
    ("run", "env"),
    [
        ('echo "A=${{ Steps.s.Outputs.v }}" >> "$GITHUB_ENV"', None),
        ('echo "A=${{ steps[\'s\'].outputs.v }}" >> "$GITHUB_ENV"', None),
        ('echo "A=${{ github.sha }}" >> ${{ github.env }}', None),
        ('echo "A=$V" >> "$GITHUB_ENV"', {"V": "${{ steps.s.outputs.v }}"}),
        ('echo "$P" >> "$GITHUB_PATH"', {"P": "${{ needs.a.outputs.p }}"}),
    ],
)
def test_env_file_writes_from_expressions_are_refused(run: str, env: dict[str, str] | None) -> None:
    step = _run(run, env=env) if env else _run(run)
    assert any("GITHUB_ENV/GITHUB_PATH" in f for f in _check(step))


def test_a_plain_env_file_write_passes() -> None:
    assert _check(_run('echo "START=$(date +%s)" >> "$GITHUB_ENV"')) == []


@pytest.mark.parametrize("trigger", ["issues", "discussion", "discussion_comment"])
def test_more_attacker_triggers_need_an_allow_list_entry(trigger: str) -> None:
    assert any(trigger in f and "allow-list" in f for f in _check({}, on={trigger: None}))


def test_a_missing_actions_dir_fails(tmp_path: Any) -> None:
    flows = tmp_path / "workflows"
    flows.mkdir()
    (flows / "ci.yml").write_text(
        "name: x\non: push\npermissions: {}\njobs: {}\n", encoding="utf-8"
    )
    assert main([str(flows), "--actions", str(tmp_path / "nope")]) == 2
