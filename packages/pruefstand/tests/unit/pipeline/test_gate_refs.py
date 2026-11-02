"""Baseline refs at gate time: PR vs main, nightly-b<k>, release-b<k> drift (T6.1, N1.4, D305)."""

from pathlib import Path

import pytest
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.promote import prepare_promotion
from structlog.testing import capture_logs
from testsupport.pipeline_support import mini_config
from testsupport.store_support import gate_run, write_gate_run

from pruefstand.core.config import BaselineStoreConfig, GatePolicy, MetricPolicy
from pruefstand.core.errors import GateInputError, StoreError
from pruefstand.pipeline.gate import gate_from_store, run_gate

BASE_ID, CAND_ID = "20261102T220000-aaaaaa", "20261102T220001-bbbbbb"
POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "error_rate": MetricPolicy(max_value=0.02),
    },
    n_resamples=500,
)
FP1, FP2 = "1" * 16, "2" * 16


def cfg(tmp_path: Path):  # type: ignore[no-untyped-def]  # PruefstandConfig
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    return mini_config(gate=POLICY, baseline_store=store)


def store_of(tmp_path: Path) -> LocalDirBaselineStore:
    return LocalDirBaselineStore(tmp_path / "store")


def test_a_block_candidate_pairs_with_its_nightly_baseline(tmp_path: Path) -> None:
    store_of(tmp_path).put(gate_run(tmp_path / "b", BASE_ID, fp=FP1, block=1), "nightly-b1")
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1, block=1)
    report = gate_from_store(candidate, cfg(tmp_path), ref="nightly-b1")
    assert report.no_baseline is False
    assert report.baseline_run_id == BASE_ID
    assert report.decisions  # paired on all 120 cases


def test_a_nightly_ref_of_another_block_is_a_gate_input_error(tmp_path: Path) -> None:
    store_of(tmp_path).put(gate_run(tmp_path / "b", BASE_ID, fp=FP1, block=1), "nightly-b1")
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1, block=1)
    with pytest.raises(GateInputError, match="block"):
        gate_from_store(candidate, cfg(tmp_path), ref="nightly-b2")


def test_an_unknown_ref_is_a_store_error(tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1, block=1)
    with pytest.raises(StoreError, match="ref"):
        gate_from_store(candidate, cfg(tmp_path), ref="nightly-b3")


def test_a_nightly_ref_for_a_candidate_without_a_block_is_a_gate_input_error(
    tmp_path: Path,
) -> None:
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1)
    with pytest.raises(GateInputError, match="block"):
        gate_from_store(candidate, cfg(tmp_path), ref="nightly-b0")


def test_drift_against_the_release_projection_uses_the_same_fingerprint(tmp_path: Path) -> None:
    from testsupport.store_support import release_run

    release = release_run(tmp_path / "rel")
    projected = prepare_promotion(release, "release-b1")
    store_of(tmp_path).put(projected, "release-b1")
    fp = projected.results.manifest.eval_fingerprint
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=fp, block=1)
    report = gate_from_store(candidate, cfg(tmp_path), ref="release-b1")
    assert report.no_baseline is False
    assert report.baseline_run_id == release.results.manifest.run_id


def test_a_release_ref_of_another_block_is_a_gate_input_error(tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1, block=1)
    with pytest.raises(GateInputError, match="block"):
        gate_from_store(candidate, cfg(tmp_path), ref="release-b2")


def test_no_release_baseline_is_a_no_baseline_report_not_an_error(tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1, block=1)
    report = gate_from_store(candidate, cfg(tmp_path), ref="release-b1")
    assert report.no_baseline is True


def test_a_block_candidate_against_the_raw_release_run_is_a_gate_input_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    release = write_gate_run(root, BASE_ID, fp=FP1, block=None)  # block None: the raw release run
    candidate = write_gate_run(root, CAND_ID, fp=FP2, block=1)
    with pytest.raises(GateInputError, match="fingerprint"):
        run_gate(candidate, release, cfg(tmp_path))


def test_a_block_one_candidate_against_a_block_two_main_run_is_a_gate_input_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    main2 = write_gate_run(root, BASE_ID, fp=FP2, block=2)
    candidate = write_gate_run(root, CAND_ID, fp=FP1, block=1)
    with pytest.raises(GateInputError, match="fingerprint"):
        run_gate(candidate, main2, cfg(tmp_path))


def test_a_pr_candidate_uses_main(tmp_path: Path) -> None:
    store_of(tmp_path).put(gate_run(tmp_path / "b", BASE_ID, fp=FP1), "main")
    candidate = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP1)
    assert gate_from_store(candidate, cfg(tmp_path)).baseline_run_id == BASE_ID


def test_run_gate_warns_when_the_config_differs_from_the_run(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    base = write_gate_run(root, BASE_ID, fp=FP1)
    candidate = write_gate_run(root, CAND_ID, fp=FP1)
    with capture_logs() as logs:
        run_gate(candidate, base, cfg(tmp_path))
    assert any(entry["event"] == "gate_config_hash_differs" for entry in logs)
