import re
from datetime import UTC, datetime
from typing import Any

import pytest

from pruefstand.core.enums import Split
from pruefstand.core.fingerprint import corpus_version, eval_fingerprint, target_fingerprint
from pruefstand.core.models.corpus import CorpusManifest
from pruefstand.core.models.target import TargetInfo


def make_manifest(**changes: Any) -> CorpusManifest:
    data: dict[str, Any] = {
        "corpus_version": "old",
        "created_at": datetime(2026, 11, 2, tzinfo=UTC),
        "sources": {"gii": "2026-10-01", "eurlex": "2026-09-01"},
        "tenants": {"kanzlei_mueller": 3, "versicherung_nord": 4},
        "sha256": {"a.jsonl": "aa" * 32, "b.jsonl": "bb" * 32},
    }
    return CorpusManifest.model_validate({**data, **changes})


def test_corpus_version_format() -> None:
    assert re.fullmatch(r"2026-11-02\.[0-9a-f]{8}", corpus_version(make_manifest(), "2026-11-02"))


def test_corpus_version_ignores_key_order() -> None:
    reordered = make_manifest(
        sources={"eurlex": "2026-09-01", "gii": "2026-10-01"},
        tenants={"versicherung_nord": 4, "kanzlei_mueller": 3},
        sha256={"b.jsonl": "bb" * 32, "a.jsonl": "aa" * 32},
    )
    assert corpus_version(reordered, "2026-11-02") == corpus_version(make_manifest(), "2026-11-02")


def test_corpus_version_ignores_own_version_and_clock() -> None:
    other = make_manifest(
        corpus_version="2026-01-01.zzzzzzzz", created_at=datetime(2030, 1, 1, tzinfo=UTC)
    )
    assert corpus_version(other, "2026-11-02") == corpus_version(make_manifest(), "2026-11-02")


def test_corpus_version_changes_with_a_checksum() -> None:
    changed = make_manifest(sha256={"a.jsonl": "cc" * 32, "b.jsonl": "bb" * 32})
    assert corpus_version(changed, "2026-11-02") != corpus_version(make_manifest(), "2026-11-02")


@pytest.mark.parametrize("tag", ["2026/11/02", "26-11-02", "2026-11-02x", "٢٠٢٦-١١-٠٢", ""])
def test_bad_date_tag(tag: str) -> None:
    with pytest.raises(ValueError, match="date_tag"):
        corpus_version(make_manifest(), tag)


def make_info(**changes: Any) -> TargetInfo:
    data: dict[str, Any] = {
        "app_version": "0.1",
        "git_sha": "abc123",
        "image_digest": "sha256:" + "d" * 64,
        "config_hash": "cfg",
        "corpus_version": "2026-11-02.ab12cd34",
        "models": {"generator": "g1", "embedding": "e1"},
        "serving": {"engine": "ollama", "quantization": "Q8_0"},
    }
    return TargetInfo.model_validate({**data, **changes})


def tfp(info: TargetInfo | None) -> str:
    return target_fingerprint(info, url="http://t", run_id="r1")


def test_target_fingerprint_digest_vs_git_sha() -> None:
    with_digest = tfp(make_info())
    without = tfp(make_info(image_digest=None))
    assert with_digest != without
    assert without == tfp(make_info(image_digest=None, app_version="9.9"))
    assert with_digest == tfp(make_info(git_sha="other"))


def test_target_fingerprint_serving_and_models() -> None:
    base = tfp(make_info())
    assert tfp(make_info(serving={"engine": "ollama", "quantization": "Q4"})) != base
    assert tfp(make_info(models={"generator": "g2", "embedding": "e1"})) != base
    assert tfp(make_info(config_hash="other")) != base
    assert tfp(make_info(corpus_version="x")) != base


def test_target_fingerprint_ignores_dict_order() -> None:
    swapped = make_info(models={"embedding": "e1", "generator": "g1"})
    assert tfp(swapped) == tfp(make_info())


def test_opaque_target_depends_on_run_id() -> None:
    a = target_fingerprint(None, url="http://t", run_id="r1")
    b = target_fingerprint(None, url="http://t", run_id="r2")
    assert a != b
    assert a == target_fingerprint(None, url="http://t", run_id="r1")


def efp(**changes: Any) -> str:
    args: dict[str, Any] = {
        "dataset_name": "pruefstand-de",
        "dataset_version": "v1",
        "splits": [Split.CORE, Split.ROBUST_PR],
        "judge_models": {"faithfulness": "ollama/gemma3:12b"},
        "judge_prompt_versions": {"faithfulness": "v1"},
        "judge_serving": {"faithfulness": "vllm 0.8.4 awq"},
        "judge_epoch": 0,
        "metric_versions": {"context_recall": "1"},
        "corpus_version": "2026-11-02.ab12cd34",
    }
    return eval_fingerprint(**{**args, **changes})


def test_eval_fingerprint_is_deterministic() -> None:
    assert efp() == efp()
    assert re.fullmatch(r"[0-9a-f]{16}", efp())


def test_eval_fingerprint_split_order_irrelevant() -> None:
    assert efp(splits=[Split.ROBUST_PR, Split.CORE]) == efp()


def test_eval_fingerprint_versions_matter() -> None:
    assert efp(judge_prompt_versions={"faithfulness": "v2"}) != efp()
    assert efp(metric_versions={"context_recall": "2"}) != efp()
    assert efp(dataset_version="v2") != efp()
    assert efp(dataset_name="other") != efp()
    assert efp(corpus_version="x") != efp()
    assert efp(splits=[Split.CORE]) != efp()
    assert efp(judge_models={"faithfulness": "ollama/other"}) != efp()


def test_tier1_empty_judges_are_stable() -> None:
    kwargs = {"judge_models": {}, "judge_prompt_versions": {}, "judge_serving": {}}
    assert efp(**kwargs) == efp(**kwargs)


def test_judge_serving_and_epoch() -> None:
    assert efp(judge_serving={"faithfulness": "vllm 0.9.0 awq"}) != efp()
    assert efp(judge_epoch=1) != efp()
    old = "ollama 0.x q4_K_M 1a2b3c4d5e6f"
    new = "ollama 0.x q4_K_M ffffffffffff"
    assert efp(judge_serving={"faithfulness": old}) != efp(judge_serving={"faithfulness": new})


def test_block_and_judged_subset() -> None:
    fps = {efp(block=None), efp(block=0), efp(block=1)}
    assert len(fps) == 3
    assert efp(judged_subset=True) != efp(judged_subset=False)
    assert efp() == efp(block=None, judged_subset=False)


def test_stratum() -> None:
    assert efp(stratum="all") == efp()
    assert efp(stratum="refusal") != efp()
    assert efp(stratum="blocks") != efp(stratum="refusal")


def test_stratum_all_keeps_the_pre_stratum_hash() -> None:
    from pruefstand.core.hashing import stable_hash

    legacy = stable_hash(
        "pruefstand-de",
        "v1",
        ["core", "robust_pr"],
        [("faithfulness", "ollama/gemma3:12b")],
        [("faithfulness", "v1")],
        [("faithfulness", "vllm 0.8.4 awq")],
        0,
        [("context_recall", "1")],
        "2026-11-02.ab12cd34",
        None,
        False,
    )
    assert efp() == legacy
