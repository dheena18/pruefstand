"""Leak, filter-bypass and system-prompt probes (T4.6 S2)."""

from collections import Counter
from pathlib import Path

from testsupport.attack_support import registry_3_tenants

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.probes import (
    make_filter_bypass_probes,
    make_leak_probes,
    make_system_prompt_probes,
)
from pruefstand.core.enums import Category, Lang
from pruefstand.core.ids import TenantId
from pruefstand.metrics.deterministic.normalise import contains_forbidden

TENANTS = tuple(TenantId(t) for t in TENANT_PREFIX)
REGISTRY = registry_3_tenants()
REPO = Path(__file__).resolve().parents[5]


def test_leak_probes_cover_all_ordered_pairs_with_one_probe_per_foreign_canary() -> None:
    probes = make_leak_probes(REGISTRY, TENANTS)
    assert len(probes) == 3 * 6
    pairs: Counter[tuple[str, str]] = Counter()
    for probe in probes:
        assert probe.category is Category.LEAK_PROBE
        assert probe.lang is Lang.DE
        owners = {c.tenant for c in REGISTRY.canaries if probe.cluster_id == c.token}
        assert len(owners) == 1
        (owner,) = owners
        assert owner != probe.tenant
        pairs[(probe.tenant, owner)] += 1
    assert len(pairs) == 6
    assert min(pairs.values()) >= 3
    assert len({p.id for p in probes}) == len(probes)


def test_probe_as_tenant_b_forbids_the_token_of_tenant_a() -> None:
    probes = make_leak_probes(REGISTRY, TENANTS)
    token = next(
        c for c in REGISTRY.canaries if c.tenant == "kanzlei_mueller" and c.kind == "token"
    )
    asked = [
        p for p in probes if p.tenant == "versicherung_nord" and token.token in p.forbidden_strings
    ]
    assert len(asked) == 1
    assert asked[0].cluster_id == token.token


def test_semantic_probe_uses_the_canary_question_and_pattern() -> None:
    probes = make_leak_probes(REGISTRY, TENANTS)
    sem = next(
        c for c in REGISTRY.canaries if c.tenant == "stadtwerke_sued" and c.kind == "semantic"
    )
    (probe,) = [p for p in probes if p.tenant == "kanzlei_mueller" and p.cluster_id == sem.token]
    assert probe.question == sem.probe_question
    assert probe.forbidden_strings == (sem.forbidden_answer,)
    assert contains_forbidden("Das sind 261 Tage.", probe.forbidden_strings[0])


def test_filter_bypass_one_probe_or_more_per_ordered_pair() -> None:
    probes = make_filter_bypass_probes(REGISTRY, TENANTS)
    assert all(p.category is Category.FILTER_BYPASS for p in probes)
    assert len({p.cluster_id for p in probes}) == len(probes)
    assert all(p.cluster_id.startswith("filter-bypass-") for p in probes)
    for asker in TENANTS:
        for other in TENANTS:
            if asker == other:
                continue
            tokens = {c.token for c in REGISTRY.canaries if c.tenant == other and c.kind == "token"}
            hits = [p for p in probes if p.tenant == asker and other in p.question]
            assert hits, (asker, other)
            for probe in hits:
                assert tokens <= set(probe.forbidden_strings)
                assert asker not in probe.question


def test_filter_bypass_forbids_every_foreign_canary_and_is_deterministic() -> None:
    a = make_filter_bypass_probes(REGISTRY, TENANTS)
    assert a == make_filter_bypass_probes(REGISTRY, TENANTS)
    foreign = {c.forbidden_answer for c in REGISTRY.foreign_to(TenantId("kanzlei_mueller"))}
    first = next(p for p in a if p.tenant == "kanzlei_mueller")
    assert set(first.forbidden_strings) == foreign


def test_system_prompt_probes_in_german_and_english() -> None:
    probes = make_system_prompt_probes()
    assert {p.lang for p in probes} == {Lang.DE, Lang.EN}
    assert {p.category for p in probes} == {Category.SYSTEM_PROMPT_EXTRACTION}
    assert not any(p.expect_refusal for p in probes)
    assert len({p.cluster_id for p in probes}) == len(probes)
    assert {p.tenant for p in probes} == set(TENANTS)
    assert probes == make_system_prompt_probes()


def test_system_prompt_sentences_are_in_the_reference_apps_prompts() -> None:
    probes = make_system_prompt_probes()
    folder = REPO / "apps/rag-demo/src/rag_demo/prompts"
    prompts = [
        (folder / name).read_text("utf-8") for name in ("answer_de_v1.txt", "answer_de_v2.txt")
    ]
    for sentence in probes[0].forbidden_strings:
        assert any(sentence in prompt for prompt in prompts), sentence
