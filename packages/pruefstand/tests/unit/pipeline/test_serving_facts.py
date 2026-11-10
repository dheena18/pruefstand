"""Judge prompt versions and serving in the fingerprint facts (T5.2b S6, T1.10a follow-up)."""

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE
from testsupport.pipeline_support import mini_config

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.judges.output import SPECS
from pruefstand.pipeline.fingerprints import judge_facts, judge_serving

POLICY = GatePolicy(metrics={"faithfulness": MetricPolicy(max_drop=0.05)})


def test_an_a40_judge_serving_names_tag_quantization_and_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    text = judge_serving("ollama/gemma3:12b")
    assert text is not None
    engine, tag, quantization, digest = text.split()
    assert (engine, tag, quantization) == ("ollama", "gemma3:12b", "Q4_K_M")
    assert len(digest) == 12


def test_a_hosted_or_unlisted_judge_has_no_serving_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    assert judge_serving("github/openai/gpt-4.1-mini") is None
    assert judge_serving("ollama/not-listed:1b") is None


def test_tier_two_facts_carry_the_prompt_version_of_every_gated_judged_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    cfg = mini_config(gate=POLICY)
    facts = judge_facts(cfg, stack="a40", tier="pr", epoch=0)
    spec = SPECS["faithfulness"]
    assert facts.prompt_versions == {"faithfulness": f"{spec.prompt_id}_{spec.version}"}


def test_tier_one_facts_stay_empty() -> None:
    facts = judge_facts(mini_config(gate=POLICY), stack="live", tier="pr", epoch=0)
    assert (facts.models, facts.prompt_versions, facts.serving) == ({}, {}, {})
