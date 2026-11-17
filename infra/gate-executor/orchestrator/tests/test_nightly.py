"""T6.2b S4: nightly scheduling helpers (pure; injected clocks and plain data)."""

from datetime import UTC, date, datetime

import pytest
from gate_orchestrator.nightly import (
    NightResult,
    RunInfo,
    cause_switches_due,
    nightly_alarm,
    nightly_judge,
    promotable,
    promotable_nightly,
    promotion_refs,
    prune_due,
    release_run_due,
)
from gate_orchestrator.window import RELEASE_REFS


def night(day: int, kind: str) -> NightResult:
    return NightResult(date(2026, 11, day), kind)  # type: ignore[arg-type]  # test literals


@pytest.mark.parametrize(
    ("present", "due"),
    [
        (set(), True),
        ({"release-b0"}, True),
        ({"release-b0", "release-b1"}, True),
        (set(RELEASE_REFS), False),
        (set(RELEASE_REFS) | {"main", "nightly-b0"}, False),
    ],
)
def test_release_run_is_due_while_any_block_anchor_is_missing(present: set[str], due: bool) -> None:  # noqa: FBT001
    assert release_run_due(present) is due


def test_cause_switches_on_a_berlin_sunday_or_when_forced() -> None:
    sunday_night = datetime(2026, 11, 8, 21, 30, tzinfo=UTC)  # 22:30 Berlin, Sunday
    saturday_evening = datetime(2026, 11, 7, 21, 30, tzinfo=UTC)  # Saturday in Berlin
    assert cause_switches_due(sunday_night) is True
    assert cause_switches_due(saturday_evening) is False
    assert cause_switches_due(saturday_evening, forced=True) is True


def test_a_job_starting_after_midnight_belongs_to_the_evening_it_was_fired() -> None:
    sunday_night_after_midnight = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)  # 00:30 Monday Berlin
    saturday_night_after_midnight = datetime(2026, 11, 7, 23, 30, tzinfo=UTC)  # 00:30 Sunday
    assert cause_switches_due(sunday_night_after_midnight) is True
    assert cause_switches_due(saturday_night_after_midnight) is False


def test_sunday_daytime_start_before_the_deadline_is_still_the_saturday_night() -> None:
    assert cause_switches_due(datetime(2026, 11, 8, 4, 0, tzinfo=UTC)) is False  # 05:00 Sunday


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        cause_switches_due(datetime(2026, 11, 8, 22, 0))  # noqa: DTZ001


@pytest.mark.parametrize(
    ("history", "alarm"),
    [
        ([], False),
        ([night(1, "none")], False),
        ([night(1, "hard")], True),  # at once
        ([night(1, "none"), night(2, "hard")], True),
        ([night(1, "statistical")], False),  # one noisy night
        ([night(1, "none"), night(2, "statistical")], False),
        ([night(1, "statistical"), night(2, "statistical")], True),  # two in a row
        ([night(1, "hard"), night(2, "statistical")], True),
        ([night(1, "statistical"), night(2, "none")], False),
    ],
)
def test_nightly_alarm_rule(history: list[NightResult], alarm: bool) -> None:  # noqa: FBT001
    assert nightly_alarm(history) is alarm


CATALOGUE = {
    "ollama/qwen3.8:27b-q8_0": {"role": "generator", "server": "gpu0"},
    "ollama/gemma3:12b": {"role": "judge", "server": "gpu1"},
    "ollama/other-judge": {"role": "judge", "server": "gpu0"},
}


def test_the_nightly_judge_is_the_catalogue_judge_on_gpu1() -> None:
    choice = nightly_judge(CATALOGUE, "ollama/gemma3:12b")
    assert (choice.judge_id, choice.judge_fallback) == ("ollama/gemma3:12b", False)


def test_a_configured_judge_missing_from_the_catalogue_is_a_fallback() -> None:
    choice = nightly_judge(CATALOGUE, "ollama/removed:70b")
    assert (choice.judge_id, choice.judge_fallback) == ("ollama/gemma3:12b", True)
    assert nightly_judge(CATALOGUE, "ollama/other-judge").judge_fallback is True  # not on gpu1


def test_a_catalogue_without_a_gpu1_judge_is_an_error() -> None:
    with pytest.raises(LookupError):
        nightly_judge({"ollama/x": {"role": "generator", "server": "gpu0"}}, "ollama/x")


def test_prune_is_due_on_the_first_poll_of_a_new_utc_month() -> None:
    assert prune_due(datetime(2026, 12, 1, 0, 3, tzinfo=UTC), (2026, 11)) is True
    assert prune_due(datetime(2026, 12, 1, 0, 3, tzinfo=UTC), (2026, 12)) is False
    assert prune_due(datetime(2026, 12, 9, 8, 0, tzinfo=UTC), (2026, 12)) is False
    assert prune_due(datetime(2027, 1, 3, 8, 0, tzinfo=UTC), (2026, 12)) is True  # day 1 was missed
    assert prune_due(datetime(2026, 11, 30, 23, 59, tzinfo=UTC), None) is True
    # 00:30 on 1 December in Berlin is still 30 November in UTC: not yet a new month
    assert prune_due(datetime(2026, 11, 30, 23, 30, tzinfo=UTC), (2026, 11)) is False


def run(run_id: str, **kw: object) -> RunInfo:
    base: dict[str, object] = {"run_id": run_id, "kind": "nightly", "block": 1, "complete": True}
    return RunInfo(**{**base, **kw})  # type: ignore[arg-type]  # test fixture


@pytest.mark.parametrize(
    "flag",
    [
        {"judge_fallback": True},
        {"judge_drift": True},
        {"judge_degraded": True},
        {"judge_truncated": True},
        {"infra_error": "data_root_unavailable"},
        {"complete": False},
        {"promoted": True},
    ],
)
def test_flagged_incomplete_or_promoted_runs_are_never_promoted(flag: dict[str, object]) -> None:
    assert promotable(run("20261110T0100-a", **flag)) is False
    assert promotable(run("20261110T0100-a")) is True


def test_the_newest_promotable_run_wins_and_flagged_ones_are_skipped() -> None:
    runs = [
        run("20261108T0100-a"),
        run("20261109T0100-b"),
        run("20261110T0100-c", judge_drift=True),
        run("20261111T0100-d", promoted=True),
    ]
    chosen = promotable_nightly(runs)
    assert chosen is not None
    assert chosen.run_id == "20261109T0100-b"
    assert promotable_nightly([run("x", complete=False)]) is None
    assert promotable_nightly([]) is None


def test_promotion_refs_of_a_block_and_of_a_release_run() -> None:
    assert promotion_refs(run("r", block=2)) == ("nightly-b2",)
    assert promotion_refs(run("r", kind="release", block=None)) == RELEASE_REFS
    with pytest.raises(ValueError, match="block"):
        promotion_refs(run("r", block=None))
    with pytest.raises(ValueError, match="block"):
        promotion_refs(run("r", block=3))
