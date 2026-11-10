"""Removing a property from a copy of the workflow makes its rule fail (T1.12 S6)."""

import pytest
from testsupport.workflow_checks import (
    check_baseline_lookup,
    check_cache_saves,
    check_comment_checkout,
    check_comment_jobs,
    check_fingerprint_rebaseline,
    check_marker,
    check_no_gate_status,
    check_no_judge_mode,
    check_secrets,
    check_uploads,
    mutated,
    read,
)


def test_removing_the_same_repo_condition_fails() -> None:
    old = "github.event.pull_request.head.repo.full_name == github.repository }}\n    runs-on"
    assert mutated(check_comment_jobs, old, "true }}\n    runs-on")


def test_a_wider_comment_permission_fails() -> None:
    old = "      contents: read\n      pull-requests: write"
    assert mutated(check_comment_jobs, old, "      contents: write\n      pull-requests: write")


@pytest.mark.parametrize("event", ["pull_request", "schedule"])
def test_changing_the_baseline_lookup_event_fails(event: str) -> None:
    old, new = "status=success&event=push", f"status=success&event={event}"
    assert mutated(check_baseline_lookup, old, new)


def test_renaming_the_schedule_upload_to_live_baseline_fails() -> None:
    old = "          name: live-baseline-nightly\n"
    assert mutated(check_uploads, old, "          name: live-baseline\n")


def test_uploading_live_baseline_on_pull_requests_fails() -> None:
    old = "        if: github.event_name == 'push' && steps.gate.outputs.run_dir != ''"
    assert mutated(check_uploads, old, "        if: steps.gate.outputs.run_dir != ''")


def test_dropping_not_gpu_from_the_marker_fails() -> None:
    assert mutated(check_marker, "e2e and not gpu and not network", "e2e and not network")


def test_a_cache_save_on_pull_requests_fails() -> None:
    old = "        if: github.ref == 'refs/heads/main' && steps.stack.outputs.models-cache-hit"
    assert mutated(check_cache_saves, old, "        if: steps.stack.outputs.models-cache-hit")


def test_a_secret_and_a_judge_mode_are_found() -> None:
    text = read("live-e2e.yml") + "\n      TOKEN: ${{ secrets.MY_PAT }}\n"
    assert check_secrets({}, text) == ["secrets.MY_PAT"]
    found = check_no_judge_mode({}, "PRUEFSTAND_JUDGE_MODE: cpu")
    assert found == ["PRUEFSTAND_JUDGE_MODE set to cpu"]
    assert check_no_gate_status({}, "context: pruefstand/gate")


def test_the_checker_comes_from_the_base_sha() -> None:
    old = "ref: ${{ github.event.pull_request.base.sha }}"
    assert mutated(check_comment_checkout, old, "ref: ${{ github.sha }}")


def test_dropping_the_fingerprint_check_fails() -> None:
    old = "uv run pruefstand baseline fingerprint-check"
    assert mutated(check_fingerprint_rebaseline, old, "uv run pruefstand version #")


def test_a_gate_error_must_still_fail_the_step() -> None:
    old = 'if [ "$gate_rc" -gt 1 ]; then exit "$gate_rc"; fi'
    assert mutated(check_fingerprint_rebaseline, old, "true")


def test_the_mismatch_note_must_stay_in_the_comment() -> None:
    assert mutated(check_fingerprint_rebaseline, "Baseline not comparable:", "Note:")
