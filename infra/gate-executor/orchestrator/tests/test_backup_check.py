"""backup-check (Y5.5, D229, A13-M10, D1095): receipt vs kept bundles; heartbeat payload merge."""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from gate_orchestrator import heartbeat_store
from gate_orchestrator.backup_check import (
    BUNDLE,
    RECEIPT,
    STALE_DAYS,
    laptop_backup_age_days,
    summary,
)
from gate_orchestrator.cli import main

NOW = datetime(2026, 11, 17, 6, 53, tzinfo=UTC)


def _backups(tmp: Path, *, sha: str | None = None, copied: str | None = None) -> Path:
    backups = tmp / "data" / "backups"
    (backups / "2026-11-15").mkdir(parents=True)
    bundle = backups / "2026-11-15" / BUNDLE
    bundle.write_bytes(b"age-encryption.org/v1 ciphertext")
    receipt = {
        "bundle": f"2026-11-15/{BUNDLE}",
        "sha256": sha or hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "copied_at": copied or (NOW - timedelta(days=3)).isoformat(),
    }
    (backups / RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    return backups


def test_matching_receipt_gives_its_age(tmp_path: Path) -> None:
    age, reason = laptop_backup_age_days(_backups(tmp_path), NOW)
    assert age == 3.0
    assert "3.0 days" in reason


@pytest.mark.parametrize(
    ("sha", "copied", "reason"),
    [
        ("0" * 64, None, "matches no kept bundle"),
        ("xyz", None, "sha256"),
        (None, "2026-11-14T06:00:00", "aware copied_at"),
    ],
)
def test_receipt_that_does_not_count_is_stale(
    tmp_path: Path, sha: str | None, copied: str | None, reason: str
) -> None:
    age, why = laptop_backup_age_days(_backups(tmp_path, sha=sha, copied=copied), NOW)
    assert age == STALE_DAYS
    assert reason in why


def test_missing_receipt_is_stale(tmp_path: Path) -> None:
    assert laptop_backup_age_days(tmp_path, NOW) == (STALE_DAYS, "no valid laptop-receipt.json")


def test_summary_warns_above_8_days() -> None:
    assert summary(8.1, "r").count("WARNING") == 1
    assert "WARNING" not in summary(8.0, "r")


def _recorder(pushed: list[Mapping[str, str]]) -> heartbeat_store.Pusher:
    def push(repo: str, payload: Mapping[str, str]) -> str:
        assert repo == heartbeat_store.DASHBOARD_REPO
        pushed.append(dict(payload))
        return "sha"

    return push


def test_update_merges_into_the_last_payload(tmp_path: Path) -> None:
    pushed: list[Mapping[str, str]] = []
    path = tmp_path / "state" / "heartbeat.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"tunnel_ok": "true", "ts": "old"}), encoding="utf-8")
    payload = heartbeat_store.update(path, {"laptop_backup_age_days": "3"}, NOW, _recorder(pushed))
    assert payload == {"tunnel_ok": "true", "laptop_backup_age_days": "3", "ts": NOW.isoformat()}
    assert pushed == [payload]
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_cli_backup_check_writes_summary_and_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backups = _backups(tmp_path)
    pushed: list[Mapping[str, str]] = []
    monkeypatch.setattr(heartbeat_store, "push_heartbeat", _recorder(pushed))
    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", str(backups.parent))
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path / "home"))
    summary_file = tmp_path / "summary.md"
    assert main(["backup-check", "--summary", str(summary_file)]) == 0
    assert "laptop backup ok" in summary_file.read_text(encoding="utf-8")
    assert pushed[0]["laptop_backup_age_days"] != str(STALE_DAYS)


def test_cli_backup_check_needs_the_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", "/nonexistent-data-root")
    assert main(["backup-check"]) == 1


def test_receipt_copied_in_the_future_is_invalid(tmp_path: Path) -> None:
    # review #224: a year ahead must not read as "0.0 days old"
    future = (NOW + timedelta(days=365)).isoformat()
    age, why = laptop_backup_age_days(_backups(tmp_path, copied=future), NOW)
    assert age == STALE_DAYS
    assert "future" in why
