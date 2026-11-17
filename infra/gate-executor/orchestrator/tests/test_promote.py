"""T6.2b S3a: promotion order and exit-code outcomes; the owner override never in a workflow."""

from pathlib import Path

import pytest
from gate_orchestrator.promote import (
    NIGHTLY_REFS,
    interpret_promote_exit,
    promotion_commands,
    valid_ref,
)
from gate_orchestrator.window import RELEASE_REFS

REPO = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("ref", ["main", *NIGHTLY_REFS])
def test_main_and_nightly_runs_are_gated_before_they_are_promoted(ref: str) -> None:
    gate, promote = promotion_commands("runs/r1", ref)
    assert gate[:2] == ["pruefstand", "gate"]
    assert gate[gate.index("--ref") + 1] == ref
    assert "--from-store" in gate
    assert promote[:3] == ["pruefstand", "baseline", "promote"]
    assert promote[promote.index("--ref") + 1] == ref


@pytest.mark.parametrize("ref", RELEASE_REFS)
def test_a_release_run_is_never_gated(ref: str) -> None:
    (promote,) = promotion_commands("runs/r1", ref)
    assert promote[:3] == ["pruefstand", "baseline", "promote"]


@pytest.mark.parametrize("ref", ["", "nightly", "nightly-b3", "release-b3", "feature", "main2"])
def test_unknown_refs_are_refused(ref: str) -> None:
    assert not valid_ref(ref)
    with pytest.raises(ValueError, match="ref"):
        promotion_commands("runs/r1", ref)


def test_no_command_carries_the_owner_override() -> None:
    for ref in ("main", *NIGHTLY_REFS, *RELEASE_REFS):
        for command in promotion_commands("runs/r1", ref):
            assert not any("allow-failed-gate" in part for part in command)


def test_exit_codes_map_to_outcomes() -> None:
    ok = interpret_promote_exit(0, "r1", "main")
    assert (ok.status, ok.record_processed, ok.alert) == ("promoted", True, False)
    refused = interpret_promote_exit(1, "r1", "main")
    assert (refused.status, refused.record_processed, refused.alert) == (
        "not_promoted",
        True,
        False,
    )
    assert "not promoted" in refused.summary
    integrity = interpret_promote_exit(3, "r1", "main")
    assert (integrity.status, integrity.record_processed, integrity.alert) == (
        "integrity_error",
        True,
        True,
    )
    for code in (2, 4, 137):
        other = interpret_promote_exit(code, "r1", "main")
        assert (other.status, other.record_processed) == (
            "error",
            False,
        )  # retried on the next poll


def test_the_owner_override_appears_in_no_executor_workflow_or_public_workflow() -> None:
    roots = [REPO / "infra" / "gate-executor", REPO / ".github" / "workflows"]
    hits = [
        str(path.relative_to(REPO))
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path != Path(__file__).resolve()
        and "allow-failed-gate" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []
