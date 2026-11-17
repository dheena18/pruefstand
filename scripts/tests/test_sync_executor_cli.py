"""sync_executor.sh refuses workflows calling a CLI subcommand the tag lacks (D1095, #214)."""

from pathlib import Path

import pytest
from sync_executor_testkit import TAG, Sandbox, git, write


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _workflow_calling(box: Sandbox, cli: str | None) -> None:
    step = "      - run: gate-orchestrator nightly --deadline x\n"
    write(
        box.public, "infra/gate-executor/workflows/nightly.yml", f"jobs:\n  n:\n    steps:\n{step}"
    )
    if cli is not None:
        write(box.public, "infra/gate-executor/orchestrator/gate_orchestrator/cli.py", cli)
    git(box.public, "add", "-A")
    git(box.public, "commit", "-q", "-m", "workflows")
    box.tag()


def test_workflows_calling_a_missing_cli_subcommand_are_refused(box: Sandbox) -> None:
    # D1095 (review #214): never sync workflows calling a gate-orchestrator subcommand the tag lacks
    _workflow_calling(box, None)
    done = box.run(TAG)
    assert done.returncode == 2
    assert "gate-orchestrator nightly" in done.stderr
    assert "sync/" + TAG not in git(box.private, "branch", "--list")


def test_workflows_calling_a_defined_subcommand_sync(box: Sandbox) -> None:
    _workflow_calling(box, 'sub.add_parser("nightly", help="x")\n')
    assert box.run(TAG).returncode == 0


@pytest.mark.parametrize(
    "step",
    [
        "      - run: gate-orchestrator  nightly --deadline x\n",
        "      - run: |\n          gate-orchestrator \\\n            nightly --deadline x\n",
        "      - run: >-\n          python3 -m gate_orchestrator\n"
        "          night-guard --event x\n",
    ],
)
def test_odd_spacing_does_not_hide_a_missing_subcommand(box: Sandbox, step: str) -> None:
    write(
        box.public, "infra/gate-executor/workflows/nightly.yml", f"jobs:\n  n:\n    steps:\n{step}"
    )
    git(box.public, "add", "-A")
    git(box.public, "commit", "-q", "-m", "workflows")
    box.tag()
    done = box.run(TAG)
    assert done.returncode == 2, done.stdout
    assert "D1095" in done.stderr
