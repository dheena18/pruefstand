"""promote-poll state and selection (R9-14, N1.4, D321, D1095): run.json shapes, ledger, prune."""

import json
from pathlib import Path
from typing import Any

from gate_orchestrator.cli import parser
from gate_orchestrator.cmd_promote import LogPoster
from gate_orchestrator.nightly import promotable_nightly, promotion_refs
from gate_orchestrator.promote_poll import last_prune, promoted_run_ids, run_info, scan_runs

from pruefstand.core.enums import GateStatus


def _manifest(run_id: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": run_id,
        "workload": "nightly",
        "block": 1,
        "stratum": "all",
        "complete": True,
        "judge_fallback": False,
        "judge_drift": False,
        "judge_degraded": False,
        "infra_error": None,
    }
    return {**base, **extra}


def _write(runs: Path, manifest: dict[str, Any]) -> None:
    run = runs / str(manifest["run_id"])
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_scan_picks_the_newest_promotable_nightly_and_its_ref(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write(runs, _manifest("20261115T2207-a"))
    _write(runs, _manifest("20261116T2207-b", block=2))
    _write(runs, _manifest("20261117T2207-c", complete=False))
    _write(runs, _manifest("20261117T0900-pr", workload="pr"))
    found = scan_runs(runs, set())
    assert set(found) == {"20261115T2207-a", "20261116T2207-b", "20261117T2207-c"}
    pick = promotable_nightly([info for info, _ in found.values()])
    assert pick is not None
    assert pick.run_id == "20261116T2207-b"
    assert promotion_refs(pick) == ("nightly-b2",)


def test_a_release_run_goes_to_all_three_release_refs(tmp_path: Path) -> None:
    info = run_info(_manifest("r", block=None), set())
    assert info is not None
    assert promotion_refs(info) == ("release-b0", "release-b1", "release-b2")


def test_flagged_or_handled_runs_are_never_picked(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write(runs, _manifest("a", judge_fallback=True))
    _write(runs, _manifest("b", infra_error="ollama_down: x"))
    _write(runs, _manifest("c"))
    ledger = tmp_path / "promoted_runs.txt"
    ledger.write_text("c nightly-b1 not_promoted\n", encoding="utf-8")
    found = scan_runs(runs, promoted_run_ids(ledger))
    assert promotable_nightly([info for info, _ in found.values()]) is None


def test_unreadable_run_json_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "runs" / "x").mkdir(parents=True)
    (tmp_path / "runs" / "x" / "run.json").write_text("{", encoding="utf-8")
    assert scan_runs(tmp_path / "runs", set()) == {}
    assert scan_runs(tmp_path / "missing", set()) == {}


def test_last_prune_marker(tmp_path: Path) -> None:
    marker = tmp_path / "last_prune"
    assert last_prune(marker) is None
    marker.write_text("2026-11\n", encoding="utf-8")
    assert last_prune(marker) == (2026, 11)
    marker.write_text("garbage", encoding="utf-8")
    assert last_prune(marker) is None


def test_log_poster_collects_lines_and_cli_registers_promote_poll() -> None:
    log = LogPoster()
    log.post_status("a" * 40, "pending", "executor busy")
    log.set_check("a" * 40, GateStatus.PASS, "promoted")
    assert log.lines == ["aaaaaaa pending: executor busy", f"aaaaaaa {GateStatus.PASS}: promoted"]
    args = parser().parse_args(["promote-poll", "--report-dir", "x"])
    assert args.report_dir == "x"
