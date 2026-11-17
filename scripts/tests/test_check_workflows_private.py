"""Private executor workflow guard (T6.2b test table, D1093): committed files pass, mutants fail."""

from pathlib import Path

import pytest
from workflow_private import check_private_dir, check_private_text, main

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "infra" / "gate-executor" / "workflows"


def _text(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def _fails(name: str, old: str, new: str, needle: str) -> None:
    text = _text(name)
    assert old in text, old
    found = check_private_text(name, text.replace(old, new, 1))
    assert any(needle in f for f in found), found


def test_committed_private_workflows_pass() -> None:
    assert check_private_dir(DIR) == (4, [])


def test_main_ok_and_missing_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(DIR)]) == 0
    assert "ok: 4 private workflows checked" in capsys.readouterr().out
    assert main([str(tmp_path / "nope")]) == 2


def test_missing_and_unexpected_files(tmp_path: Path) -> None:
    (tmp_path / "other.yml").write_text(_text("backup.yml"), encoding="utf-8")
    _, found = check_private_dir(tmp_path)
    assert any("missing gate-executor.yml" in f for f in found)
    assert any("unexpected private workflow other.yml" in f for f in found)


@pytest.mark.parametrize(
    ("name", "old", "new", "needle"),
    [
        ("gate-executor.yml", "runs-on: [self-hosted, linux, a40]", "runs-on: ubuntu-24.04", "a40"),
        ("gate-executor.yml", "-${{ inputs.pr || inputs.sha }}", "", "concurrency.group"),
        (
            "baseline-promote.yml",
            "group: ${{ github.workflow }}",
            "group: gpu-cluster",
            "concurrency",
        ),
        (
            "backup.yml",
            "cancel-in-progress: false",
            "cancel-in-progress: true",
            "cancel-in-progress",
        ),
        (
            "gate-executor.yml",
            "  workflow_dispatch:\n",
            '  schedule:\n    - cron: "7 * * * *"\n  workflow_dispatch:\n',
            "only trigger",
        ),
        ("baseline-promote.yml", "11,26,41,56 * * * *", "11,26,45,56 * * * *", "0/15/30/45"),
        (
            "backup.yml",
            "  workflow_dispatch:\n",
            "  push:\n  workflow_dispatch:\n",
            "triggers must be",
        ),
        ("nightly.yml", "7 21 * * *", "7 22 * * *", "nightly crons"),
        (
            "nightly.yml",
            "if: needs.guard.outputs.run == 'true'",
            "if: always()",
            "needs guard and if",
        ),
        ("nightly.yml", "outputs:\n      run:", "outputs:\n      go:", "outputs run and deadline"),
        ("nightly.yml", '--schedule "$SCHEDULE"', "", "night-guard --schedule"),
        (
            "nightly.yml",
            "gate-orchestrator nightly --deadline",
            "gate-orchestrator nightly",
            "nightly --deadline",
        ),
        ("nightly.yml", "    timeout-minutes: 470\n", "", "timeout-minutes"),
        (
            "nightly.yml",
            "  nightly:\n    name: nightly",
            "  mutmut:\n    name: mutmut",
            "exactly the jobs",
        ),
        (
            "nightly.yml",
            "    runs-on: ubuntu-24.04",
            "    runs-on: [self-hosted, linux, a40]",
            "hosted ubuntu",
        ),
        (
            "nightly.yml",
            "          PYTHONPATH:",
            "          X: ${{ secrets.BOT_APP_KEY }}\n          PYTHONPATH:",
            "uses a secret",
        ),
        (
            "backup.yml",
            "run: infra/gate-executor/host/backup.sh",
            "run: flock /x infra/gate-executor/host/backup.sh",
            "flock",
        ),
        (
            "baseline-promote.yml",
            "run: gate-orchestrator promote-poll",
            "run: switch-mode.sh night && gate-orchestrator promote-poll",
            "infra/gpu",
        ),
        ("baseline-promote.yml", "retention-days: 14", "retention-days: 90", "retention-days"),
        ("gate-executor.yml", "# v7.0.1", "", "vX.Y.Z"),
        ("backup.yml", "permissions: {}\n", "permissions: write-all\n", "top-level permissions"),
        ("gate-executor.yml", "PR number of", "run-gate PR number of", "run-gate"),
    ],
)
def test_mutant_fails(name: str, old: str, new: str, needle: str) -> None:
    _fails(name, old, new, needle)


def test_dispatch_of_baseline_promote_fails() -> None:
    text = _text("nightly.yml").replace(
        '            --report-dir "$REPORT_DIR"',
        '            --report-dir "$REPORT_DIR"\n          gh workflow run baseline-promote.yml',
    )
    assert any("dispatches baseline-promote" in f for f in check_private_text("nightly.yml", text))


def test_backup_reads_the_recipient_from_an_actions_variable_and_fetches_nothing() -> None:
    text = _text("backup.yml")
    assert "AGE_RECIPIENT: ${{ vars.AGE_RECIPIENT }}" in text
    assert "extraheader" not in text
    assert "fetch-depth: 0" in text


@pytest.mark.parametrize(
    ("name", "old", "new", "needle"),
    [
        # review #214, finding 1: each mutant slipped through before
        (
            "nightly.yml",
            '--deadline-input "$DEADLINE_INPUT"',
            '--deadline-input "${{ inputs.deadline }}"',
            "inside run:",
        ),
        ("gate-executor.yml", '--pr "$PR"', '--pr "${{ inputs.pr }}"', "inside run:"),
        (
            "nightly.yml",
            "    permissions:\n      contents: read\n    outputs:",
            "    permissions: write-all\n    outputs:",
            "exactly {contents: read}",
        ),
        (
            "gate-executor.yml",
            "      contents: write  #",
            "      actions: write\n      contents: write  #",
            "exactly {contents: read|write}",
        ),
        (
            "gate-executor.yml",
            "      contents: write  #",
            "      id-token: write\n      contents: write  #",
            "exactly {contents: read|write}",
        ),
        (
            "gate-executor.yml",
            "          persist-credentials: false\n",
            "",
            "persist-credentials: false",
        ),
        (
            "baseline-promote.yml",
            'run: gate-orchestrator promote-poll --report-dir "$REPORT_DIR"',
            'run: gate-orchestrator promote-poll --token "$STATE_TOKEN" --report-dir "$REPORT_DIR"',
            "$STATE_TOKEN on a command line",
        ),
        (
            "backup.yml",
            "run: gate-orchestrator backup-check",
            "run: echo ${DASHBOARD_DATA_PAT} | gate-orchestrator backup-check",
            "$DASHBOARD_DATA_PAT on a command line",
        ),
        (
            "backup.yml",
            "run: gate-orchestrator backup-check",
            "run: X=${{ secrets.DASHBOARD_DATA_PAT }} gate-orchestrator backup-check",
            "inside run:",
        ),
        (
            "gate-executor.yml",
            "runs-on: [self-hosted, linux, a40]",
            "runs-on: [self-hosted, a40]",
            "[self-hosted, linux, a40]",
        ),
        (
            "backup.yml",
            "run: gate-orchestrator backup-check",
            "run: echo secrets.DASHBOARD_DATA_PAT; gate-orchestrator backup-check",
            "secrets.* inside run:",
        ),
        (
            "gate-executor.yml",
            "      contents: write  #",
            "      contents: none  #",
            "exactly {contents: read|write}",
        ),
        # finding 6: rules that had no mutant test
        (
            "gate-executor.yml",
            "        required: true\n",
            "        required: false\n",
            "required input pr",
        ),
        (
            "nightly.yml",
            "DEADLINE: ${{ needs.guard.outputs.deadline }}",
            "DEADLINE: ${{ inputs.deadline }}",
            "nightly --deadline",
        ),
        (
            "backup.yml",
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            "actions/checkout@v7 # v7.0.1",
            "40-hex",
        ),
    ],
)
def test_review_214_mutant_fails(name: str, old: str, new: str, needle: str) -> None:
    _fails(name, old, new, needle)


def test_findings_name_the_file_once() -> None:
    text = _text("gate-executor.yml").replace(
        "        required: true\n", "        required: false\n"
    )
    (finding,) = [f for f in check_private_text("gate-executor.yml", text) if "required" in f]
    assert finding.count("gate-executor.yml") == 1


def test_any_token_output_on_a_command_line_fails() -> None:
    # review #214 minor: TOKEN_VALUE must know more than `outputs.token`
    text = (
        _text("gate-executor.yml")
        .replace(
            "          STATE_TOKEN: ${{ github.token }}\n",
            "          STATE_TOKEN: ${{ github.token }}\n"
            "          TOK: ${{ steps.app.outputs.app-token }}\n",
        )
        .replace('--pr "$PR"', '--pr "$PR" --token "$TOK"')
    )
    assert any("$TOK on a command line" in f for f in check_private_text("gate-executor.yml", text))
