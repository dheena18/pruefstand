"""Promotion rules and the block-k projection of the release run (T6.1, D321, N1.4)."""

from pathlib import Path
from typing import Any

import pytest
from pruefstand.store.promote import prepare_promotion
from testsupport.store_support import FP, full_cases, release_run, run_id, run_of

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.fingerprint import eval_fingerprint


def block_fingerprint(block: int) -> str:
    """What the nightly of block ``block`` computes (``stratum="all"``, same dataset)."""
    return eval_fingerprint(
        dataset_name="pruefstand-de",
        dataset_version="v1",
        splits=[Split.FULL],
        judge_models={},
        judge_prompt_versions={},
        judge_serving={},
        judge_epoch=0,
        metric_versions={"context_recall": "1"},
        corpus_version="2026-11-02.ab12cd34",
        block=block,
        stratum="all",
    )


def test_a_main_run_without_a_block_is_promoted_as_is(tmp_path: Path) -> None:
    run = run_of(tmp_path)
    assert prepare_promotion(run, "main") == run


def test_main_refuses_a_block_run(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="block"):
        prepare_promotion(run_of(tmp_path, block=1), "main")


def test_nightly_needs_the_matching_block(tmp_path: Path) -> None:
    run = run_of(tmp_path, block=1)
    assert prepare_promotion(run, "nightly-b1") == run
    with pytest.raises(ConfigError, match="block"):
        prepare_promotion(run, "nightly-b2")
    with pytest.raises(ConfigError, match="block"):
        prepare_promotion(run_of(tmp_path), "nightly-b0")


@pytest.mark.parametrize("ref", ["release", "nightly-b3", "foo", "../main"])
def test_an_unknown_ref_is_a_usage_error(tmp_path: Path, ref: str) -> None:
    with pytest.raises(ConfigError, match="ref"):
        prepare_promotion(run_of(tmp_path), ref)


def test_a_block_run_cannot_become_a_release_anchor(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="release"):
        prepare_promotion(run_of(tmp_path, block=1), "release-b1")


def test_a_stratum_run_cannot_become_a_release_anchor(tmp_path: Path) -> None:
    run = release_run(tmp_path, stratum="refusal")
    with pytest.raises(ConfigError, match="stratum"):
        prepare_promotion(run, "release-b1")


@pytest.mark.parametrize("block", [0, 1, 2])
def test_the_release_projection_is_refusal_stratum_plus_block_k(tmp_path: Path, block: int) -> None:
    release = release_run(tmp_path)
    projected = prepare_promotion(release, f"release-b{block}")
    cases = [s.case for s in projected.results.values]
    assert {c.block for c in cases} == {None, block}
    assert len(cases) == 2 + 2  # two refusal cases, two cases of the block
    assert [r.case_id for r in projected.results.records] == [c.id for c in cases]
    manifest = projected.results.manifest
    assert manifest.block == block
    assert manifest.n_cases == 4
    assert manifest.stratum == "all"
    assert manifest.complete
    assert manifest.run_id == run_id(50)


@pytest.mark.parametrize("block", [0, 1, 2])
def test_the_projection_has_exactly_the_fingerprint_of_the_nightly_of_that_block(
    tmp_path: Path, block: int
) -> None:
    release = release_run(tmp_path, splits=[Split.FULL], metric_versions={"context_recall": "1"})
    projected = prepare_promotion(release, f"release-b{block}")
    assert projected.results.manifest.eval_fingerprint == block_fingerprint(block)
    assert release.results.manifest.eval_fingerprint == FP  # the source is untouched


def test_the_projection_leaves_the_release_run_unchanged(tmp_path: Path) -> None:
    release = release_run(tmp_path)
    before = release.model_dump_json()
    prepare_promotion(release, "release-b1")
    assert release.model_dump_json() == before


def test_the_projection_recounts_what_it_can(tmp_path: Path) -> None:
    release = release_run(tmp_path, counts={"ok": 8, "cached": 8, "model_reloads": 2})
    counts = prepare_promotion(release, "release-b2").results.manifest.counts
    assert counts["ok"] == 4
    assert counts.get("cached", 0) == 0
    assert "model_reloads" not in counts  # a run-level counter that cannot be split by case


def test_mixed_corpus_versions_cannot_be_projected(tmp_path: Path) -> None:
    release = release_run(tmp_path)
    first = release.results.values[0]
    other = first.case.model_copy(update={"corpus_version": "2026-01-01.00000000"})
    values = (first.model_copy(update={"case": other}), *release.results.values[1:])
    mixed = release.model_copy(
        update={"results": release.results.model_copy(update={"values": values})}
    )
    with pytest.raises(StoreError, match="corpus"):
        prepare_promotion(mixed, "release-b0")


@pytest.mark.parametrize(
    "changes",
    [{"judge_fallback": True}, {"judge_drift": True}, {"judge_degraded": True}],
)
def test_flagged_release_runs_are_never_projected(tmp_path: Path, changes: dict[str, Any]) -> None:
    with pytest.raises(StoreError, match="judge"):
        prepare_promotion(release_run(tmp_path, **changes), "release-b0")


def test_the_full_split_has_the_expected_shape() -> None:
    assert len(full_cases()) == 8
