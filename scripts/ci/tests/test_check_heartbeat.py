"""check_heartbeat (T6.2b S8, D1092): a pure function of now, file and open issues."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ci.check_heartbeat import Action, evaluate, main, parse

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _hb(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ts": (NOW - timedelta(minutes=30)).isoformat(),
        "tunnel_ok": True,
        "ollama_gpu0_ok": True,
        "ollama_gpu1_ok": True,
        "data_root_ok": True,
        "tunnel_ok_false_since": "",
        "ollama_gpu0_ok_false_since": "",
        "ollama_gpu1_ok_false_since": "",
        "data_root_ok_false_since": "",
        "laptop_backup_age_days": 3,
        "last_nightly_result": "success",
        "last_nightly_status": "ok",
        "last_nightly_at": (NOW - timedelta(hours=10)).isoformat(),
        "maintenance": False,
    }
    return {**base, **changes}


def _ops(actions: list[Action]) -> dict[str, str]:
    return {a.label: a.op for a in actions}


def _ago(**delta: float) -> str:
    return (NOW - timedelta(**delta)).isoformat()


def test_fresh_healthy_heartbeat_needs_no_action() -> None:
    assert evaluate(_hb(), NOW, open_labels=set()) == []


def test_stale_ts_opens_executor_down_with_the_age() -> None:
    (action,) = evaluate(_hb(ts=_ago(hours=2, minutes=1)), NOW, open_labels=set())
    assert (action.label, action.op) == ("executor-down", "open")
    assert "2 h 1 min" in action.body


@pytest.mark.parametrize("hb", [None, {"ts": "not a time"}, {"no_ts": 1}])
def test_missing_or_unparsable_heartbeat_is_down(hb: dict[str, Any] | None) -> None:
    assert _ops(evaluate(hb, NOW, open_labels=set())) == {"executor-down": "open"}


def test_health_field_false_for_more_than_2_h_is_down_naming_it() -> None:
    hb = _hb(tunnel_ok=False, tunnel_ok_false_since=_ago(hours=2, minutes=1))
    (action,) = evaluate(hb, NOW, open_labels=set())
    assert action.label == "executor-down"
    assert "tunnel_ok" in action.body
    hb = _hb(tunnel_ok=False, tunnel_ok_false_since=_ago(hours=1, minutes=59))
    assert evaluate(hb, NOW, open_labels=set()) == []


def test_heartbeats_every_15_min_over_an_8_h_nightly_never_alert() -> None:
    for step in range(33):
        now = NOW + timedelta(minutes=15 * step)
        hb = _hb(ts=(now - timedelta(minutes=14)).isoformat(), last_nightly_at=_ago(hours=1))
        assert "executor-down" not in _ops(evaluate(hb, now, open_labels=set()))


def test_backup_stale_opens_and_closes() -> None:
    assert _ops(evaluate(_hb(laptop_backup_age_days=9), NOW, open_labels=set())) == {
        "backup-stale": "open"
    }
    assert _ops(evaluate(_hb(), NOW, open_labels={"backup-stale"})) == {"backup-stale": "close"}


def test_failed_nightly_opens_nightly_failed() -> None:
    hb = _hb(last_nightly_result="failure")
    assert _ops(evaluate(hb, NOW, open_labels=set())) == {"nightly-failed": "open"}


def test_no_completed_nightly_for_26_h_is_skipped() -> None:
    hb = _hb(last_nightly_at=_ago(hours=26, minutes=1))
    assert _ops(evaluate(hb, NOW, open_labels=set())) == {"nightly-skipped": "open"}
    hb = _hb(last_nightly_at=_ago(hours=25, minutes=59))
    assert evaluate(hb, NOW, open_labels=set()) == []


@pytest.mark.parametrize(
    "status", ["skipped: maintenance", "aborted: window_exceeded", "skipped: runner busy"]
)
def test_skipped_or_aborted_status_opens_nightly_skipped_naming_it(status: str) -> None:
    (action,) = evaluate(_hb(last_nightly_status=status), NOW, open_labels=set())
    assert (action.label, action.op) == ("nightly-skipped", "open")
    assert status in action.body


def test_ok_closes_nightly_skipped() -> None:
    assert _ops(evaluate(_hb(), NOW, open_labels={"nightly-skipped"})) == {
        "nightly-skipped": "close"
    }


def test_maintenance_suppresses_health_fields_but_not_a_stale_ts() -> None:
    hb = _hb(maintenance=True, ollama_gpu1_ok=False, ollama_gpu1_ok_false_since=_ago(hours=3))
    assert "executor-down" not in _ops(evaluate(hb, NOW, open_labels=set()))
    hb["ts"] = _ago(hours=2, minutes=1)
    assert _ops(evaluate(hb, NOW, open_labels=set()))["executor-down"] == "open"


def test_drift_without_release_baseline_is_mentioned_once_per_tag() -> None:
    hb = _hb(drift_no_release_baseline=True, release_tag="v0.3.0")
    first = [a for a in evaluate(hb, NOW, open_labels=set()) if a.marker]
    assert [(a.label, a.op, a.marker) for a in first] == [
        ("nightly-skipped", "open", "drift-no-release:v0.3.0")
    ]
    again = evaluate(hb, NOW, open_labels={"nightly-skipped"}, markers={"drift-no-release:v0.3.0"})
    assert [a for a in again if a.marker] == []


@pytest.mark.parametrize(
    ("hb", "open_labels", "op"),
    [
        (_hb(ts="2026-11-16T09:00:00+00:00"), set(), "open"),
        (_hb(ts="2026-11-16T09:00:00+00:00"), {"executor-down"}, "comment"),
        (_hb(), {"executor-down"}, "close"),
    ],
)
def test_issue_action_per_state(hb: dict[str, Any], open_labels: set[str], op: str) -> None:
    assert _ops(evaluate(hb, NOW, open_labels=open_labels))["executor-down"] == op


def test_parse_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert parse("{bad") is None
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps(_hb(laptop_backup_age_days=9)), encoding="utf-8")
    code = main(["--heartbeat", str(path), "--now", NOW.isoformat(), "--open", "nightly-failed"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert {(a["label"], a["op"]) for a in out} == {
        ("backup-stale", "open"),
        ("nightly-failed", "close"),
    }


ALL_OPEN = {"executor-down", "backup-stale", "nightly-failed", "nightly-skipped"}
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "executor-health.yml"


@pytest.mark.parametrize(
    "hb",
    [None, {}, {"ts": "not a time"}, _hb(ts="2026-11-16T09:00:00+00:00", last_nightly_status="ok")],
)
def test_unknown_or_stale_state_closes_nothing(hb: dict[str, Any] | None) -> None:
    # review #198: an empty, failed-fetch or stale heartbeat must never close an alert
    actions = evaluate(hb, NOW, open_labels=ALL_OPEN)
    assert [a for a in actions if a.op == "close"] == []
    assert _ops(actions)["executor-down"] == "comment"


def test_failing_health_field_closes_nothing() -> None:
    hb = _hb(data_root_ok=False, data_root_ok_false_since=_ago(hours=3))
    assert [a for a in evaluate(hb, NOW, open_labels=ALL_OPEN) if a.op == "close"] == []


def test_fresh_healthy_heartbeat_closes_every_open_alert() -> None:
    assert _ops(evaluate(_hb(), NOW, open_labels=ALL_OPEN)) == dict.fromkeys(ALL_OPEN, "close")


@pytest.mark.parametrize(
    "tag", ["@someone", "v1 [x](https://evil.example)", "a" * 65, "", 7, "v1\nx"]
)
def test_unsafe_release_tag_is_replaced(tag: object) -> None:
    hb = _hb(drift_no_release_baseline=True, release_tag=tag)
    (action,) = [a for a in evaluate(hb, NOW, open_labels=set()) if a.marker]
    assert action.marker == "drift-no-release:invalid-tag"
    assert "@" not in action.body
    assert "http" not in action.body


def test_unsafe_status_text_is_neutralised() -> None:
    hb = _hb(last_nightly_status="skipped: @someone see https://evil.example `x`")
    (action,) = evaluate(hb, NOW, open_labels=set())
    assert "@" not in action.body
    assert "https:" not in action.body
    assert action.body.count("`") == 2


@pytest.mark.parametrize("tag", ["v0.3.0", "v1.0.0-rc_1", "x" * 64])
def test_marker_is_found_by_the_workflow_regex(tag: str) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    pattern = re.search(r"grep -oE '([^']+)'", text)
    assert pattern is not None
    hb = _hb(drift_no_release_baseline=True, release_tag=tag)
    (action,) = [a for a in evaluate(hb, NOW, open_labels=set()) if a.marker]
    assert re.findall(pattern.group(1), action.body) == [action.marker]


@pytest.mark.parametrize("field", ["tunnel_ok", "ollama_gpu0_ok", "ollama_gpu1_ok", "data_root_ok"])
def test_partial_heartbeat_missing_a_health_field_closes_nothing(field: str) -> None:
    # review #198 minor 1: a missing health field is unknown, not healthy
    hb = _hb()
    del hb[field]
    assert [a for a in evaluate(hb, NOW, open_labels=ALL_OPEN) if a.op == "close"] == []


@pytest.mark.parametrize("value", [None, "true", 1])
def test_non_bool_health_field_closes_nothing(value: object) -> None:
    hb = _hb(tunnel_ok=value)
    assert [a for a in evaluate(hb, NOW, open_labels=ALL_OPEN) if a.op == "close"] == []


@pytest.mark.parametrize(
    ("label", "field"),
    [("backup-stale", "laptop_backup_age_days"), ("nightly-failed", "last_nightly_result")],
)
def test_missing_own_field_keeps_that_issue_open(label: str, field: str) -> None:
    hb = _hb()
    del hb[field]
    assert label not in _ops(evaluate(hb, NOW, open_labels={label}))


def test_unparsable_backup_age_keeps_backup_stale_open() -> None:
    hb = _hb(laptop_backup_age_days="3")
    assert "backup-stale" not in _ops(evaluate(hb, NOW, open_labels={"backup-stale"}))


def test_close_and_drift_note_in_one_run_are_independent() -> None:
    # review #198 minor 2: a drift note must not be a comment on the issue closed in the same run
    hb = _hb(drift_no_release_baseline=True, release_tag="v0.3.0")
    actions = evaluate(hb, NOW, open_labels={"nightly-skipped"})
    assert [(a.op, a.marker) for a in actions] == [
        ("close", ""),
        ("open", "drift-no-release:v0.3.0"),
    ]


def test_workflow_comment_without_open_issue_creates_one() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "open|comment)" in text
