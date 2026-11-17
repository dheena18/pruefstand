"""Gate result / pending posting only on change (interfaces §10, X4.6, P4.2, D103)."""

import pytest
from gate_orchestrator.report import current_gate_status, post_gate_result, post_state
from orch_testkit import SpyPoster

from pruefstand.core.enums import GateStatus

SHA = "e" * 40
FP = "fp-1a2b3c"


def test_fail_goes_through_set_check(poster: SpyPoster) -> None:
    assert post_gate_result(
        poster,
        SHA,
        status=GateStatus.FAIL,
        summary="2 checks failed",
        no_baseline=False,
        current=None,
    )
    assert poster.calls == [("set_check", SHA, "fail", "2 checks failed", "False", "False")]


@pytest.mark.parametrize("status", [GateStatus.PASS, GateStatus.WARN, GateStatus.INSUFFICIENT_DATA])
def test_no_baseline_is_set_check_with_no_baseline(poster: SpyPoster, status: GateStatus) -> None:
    post_gate_result(poster, SHA, status=status, summary=FP, no_baseline=True, current=None)
    assert poster.calls == [("set_check", SHA, str(status), FP, "True", "False")]


def test_same_failure_already_set_posts_nothing(poster: SpyPoster) -> None:
    current = ("failure", f"no baseline for {FP}; run baseline-promote")
    posted = post_gate_result(
        poster, SHA, status=GateStatus.PASS, summary=FP, no_baseline=True, current=current
    )
    assert not posted
    assert poster.calls == []


def test_a_changed_description_posts_again(poster: SpyPoster) -> None:
    current = ("success", "PASS: old summary")
    assert post_gate_result(
        poster,
        SHA,
        status=GateStatus.PASS,
        summary="new summary",
        no_baseline=False,
        current=current,
    )


def test_pending_through_post_status_only_on_change(poster: SpyPoster) -> None:
    text = "awaiting signed image; dispatch again after build-images"
    assert post_state(poster, SHA, "pending", text, None)
    assert not post_state(poster, SHA, "pending", text, ("pending", text))
    assert poster.calls == [("post_status", SHA, "pending", text, "pruefstand/gate")]


def test_current_gate_status_picks_the_gate_context() -> None:
    statuses = [
        {"context": "pruefstand/image", "state": "success", "description": "sha256:…"},
        {
            "context": "pruefstand/gate",
            "state": "pending",
            "description": "gated: awaiting tier-2 dispatch",
        },
    ]
    assert current_gate_status(statuses) == ("pending", "gated: awaiting tier-2 dispatch")
    assert current_gate_status(statuses[:1]) is None
