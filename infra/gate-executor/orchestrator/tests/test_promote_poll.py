"""promote-poll state and selection (R9-14, N1.4, D321, D1095): run.json shapes, ledger, prune."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from gate_orchestrator.cli import parser
from gate_orchestrator.cmd_nightly import public_reader
from gate_orchestrator.cmd_promote import LogPoster, PollDeps, run_poll
from gate_orchestrator.nightly import promotable_nightly, promotion_refs
from gate_orchestrator.promote_poll import handled_refs, last_prune, run_info, scan_runs

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
    found = scan_runs(runs, handled_refs(ledger))
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


# --- review #236: the poll through run_poll with a scripted host and tmp state ---------------

REPO = Path(__file__).resolve().parents[4]
HEAD = "c" * 40
IMAGE = {"context": "pruefstand/image", "state": "success", "description": "sha256:" + "d" * 64}


class _Reader:
    def __init__(self, head: str | None) -> None:
        self.head = head

    def branch_head(self, branch: str) -> str | None:
        assert branch == "main"
        return self.head

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        return [IMAGE]


def _deps(
    tmp: Path, codes: dict[str, list[int]], *, head: str | None = None, job_result: str = ""
) -> tuple[PollDeps, list[list[str]]]:
    calls: list[list[str]] = []

    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        calls.append(args)
        ref = args[args.index("--ref") + 1] if "--ref" in args else ""
        key = f"{args[1]}:{ref}"
        return (codes[key].pop(0) if codes.get(key) else 0), ""

    deps = PollDeps(
        env={"PRUEFSTAND_HOME": str(tmp / "home"), "PRUEFSTAND_MAIN_DIR": str(REPO)},
        reader=_Reader(head),
        run=run,
        run_job=lambda attempt, health: job_result,
        now=lambda: datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
    )
    (tmp / "home" / "state").mkdir(parents=True)
    (tmp / "home" / "state" / "last_prune").write_text("2026-11\n", encoding="utf-8")
    return deps, calls


def test_a_transient_release_ref_is_retried_and_only_final_refs_are_recorded(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "home" / "runs", _manifest("rel1", block=None))
    deps, calls = _deps(tmp_path, {"baseline:release-b1": [5, 0]})
    run_poll(deps, tmp_path / "work")
    ledger = tmp_path / "home" / "state" / "promoted_runs.txt"
    assert handled_refs(ledger) == {("rel1", "release-b0"), ("rel1", "release-b2")}
    calls.clear()
    run_poll(deps, tmp_path / "work")
    promoted = [c[c.index("--ref") + 1] for c in calls if c[1] == "baseline"]
    assert promoted == ["release-b1"]
    assert handled_refs(ledger) == {("rel1", f"release-b{k}") for k in range(3)}
    calls.clear()
    run_poll(deps, tmp_path / "work")
    assert [c for c in calls if c[1] == "baseline"] == []


def test_a_crashed_nightly_gate_is_not_recorded(tmp_path: Path) -> None:
    _write(tmp_path / "home" / "runs", _manifest("n1", block=0))
    deps, calls = _deps(tmp_path, {"gate:nightly-b0": [3]})
    run_poll(deps, tmp_path / "work")
    assert handled_refs(tmp_path / "home" / "state" / "promoted_runs.txt") == set()
    assert not any(c[1] == "baseline" for c in calls)


@pytest.mark.parametrize(
    ("result", "recorded"),
    [
        ("promoted r1 to main", True),
        ("not promoted: r1 to main (refused)", True),
        ("not run (maintenance or busy)", False),
        ("error: repair_failed: health.sh exit 1", False),
    ],
)
def test_the_main_head_is_recorded_only_for_a_final_outcome(
    tmp_path: Path, result: str, *, recorded: bool
) -> None:
    deps, _ = _deps(tmp_path, {}, head=HEAD, job_result=result)
    run_poll(deps, tmp_path / "work")
    marker = tmp_path / "home" / "state" / "promote_main_sha"
    assert marker.exists() is recorded


def test_the_poll_reads_the_public_repo_anonymously() -> None:
    assert "authorization" not in {k.lower() for k in public_reader()._client.headers}
