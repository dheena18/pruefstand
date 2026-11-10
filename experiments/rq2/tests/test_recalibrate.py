"""T5.4 S11: re-calibration bumps judge_epoch only on a pass (X3.3, D163); drift flags (D253)."""

from pathlib import Path

from rq2.recalibrate import after_anchor_rerun, apply_recalibration
from rq2.status_file import read_document, write_document

from pruefstand.core.enums import Split
from pruefstand.llm.cache_epochs import DriftFlag, read_drift
from pruefstand.pipeline.fingerprints import JudgeFacts, build_eval_fingerprint
from pruefstand.pipeline.judge_drift import DriftResult

JUDGE = "ollama/gemma3:12b"


def _flag(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    flag = DriftFlag(model=JUDGE, agreement=0.9, epoch=1, ts="2026-11-10T03:00:00+00:00", changed=5)
    (cache / "judge_drift.json").write_text(flag.model_dump_json(), encoding="utf-8")


def _fingerprint(epoch: int) -> str:
    return build_eval_fingerprint(
        JudgeFacts({}, {}, {}, epoch),
        name="d",
        version="1",
        corpus_version="c",
        splits=[Split.CORE],
        metric_versions={},
    )


def test_a_passing_anchor_rerun_clears_a_local_flag_without_an_epoch_bump(tmp_path: Path) -> None:
    status = tmp_path / "status.yaml"
    write_document({"epoch": 1, "passed": True}, status)
    _flag(tmp_path / "cache")
    assert after_anchor_rerun(JUDGE, DriftResult("ok", 50, 0.98, 1, 5), tmp_path / "cache")
    assert read_drift(tmp_path / "cache") is None
    assert read_document(status)["epoch"] == 1


def test_a_passing_recalibration_bumps_the_epoch_and_clears_the_flag(tmp_path: Path) -> None:
    status = tmp_path / "status.yaml"
    write_document({"epoch": 1, "passed": True}, status)
    _flag(tmp_path / "cache")
    epoch = apply_recalibration(
        JUDGE, passed=True, cache_dir=tmp_path / "cache", status_path=status
    )
    assert epoch == 2
    assert read_document(status)["epoch"] == 2
    assert read_drift(tmp_path / "cache") is None
    assert _fingerprint(1) != _fingerprint(2)


def test_a_failing_recalibration_keeps_epoch_and_flag(tmp_path: Path) -> None:
    status = tmp_path / "status.yaml"
    write_document({"epoch": 1, "passed": False}, status)
    _flag(tmp_path / "cache")
    epoch = apply_recalibration(
        JUDGE, passed=False, cache_dir=tmp_path / "cache", status_path=status
    )
    assert epoch == 1
    assert read_drift(tmp_path / "cache") is not None
