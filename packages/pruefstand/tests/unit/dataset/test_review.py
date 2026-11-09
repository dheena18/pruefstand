"""Review sampling, decisions, error rates, smoke selection and the spot-check rules (T4.7a)."""

from collections import Counter
from datetime import UTC, date, datetime

import pytest
from testsupport.review_support import REVIEW_DAY, build_cases, item

from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.dataset import ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.review import (
    apply_decisions,
    error_rates,
    sample_for_review,
    sample_spotcheck,
    select_smoke,
    spotcheck_trust,
    stratum_of,
)

PROBES = {Category.LEAK_PROBE, Category.INJECTION, Category.SYSTEM_PROMPT_EXTRACTION}


def _full_pool() -> list[TestCase]:
    cases = build_cases(
        Split.FULL,
        {
            (Category.FACTUAL, "qa_factual_de_v1"): 300,
            (Category.FACTUAL, "qa_factual_de_v2"): 100,
            (Category.MULTI_HOP, "qa_multi_hop_de_v1"): 250,
            (Category.COMPARISON, "qa_comparison_de_v1"): 150,
            (Category.CROSS_LINGUAL, "qa_cross_lingual_de_v1"): 100,
            (Category.UNANSWERABLE, None): 100,
            (Category.LEAK_PROBE, None): 10,
            (Category.INJECTION, None): 5,
        },
    )
    return (
        cases
        + build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 20}, "core")
        + (build_cases(Split.SMOKE, {(Category.FACTUAL, "qa_factual_de_v1"): 5}, "smoke"))
    )


def test_sampler_takes_a_fifth_per_stratum_and_every_probe() -> None:
    cases = _full_pool()
    chosen = sample_for_review(cases, seed=3)
    by_stratum = Counter(stratum_of(c) for c in chosen if c.split is Split.FULL)
    assert by_stratum["factual/qa_factual_de_v1"] == 60
    assert by_stratum["factual/qa_factual_de_v2"] == 20
    assert by_stratum["multi_hop/qa_multi_hop_de_v1"] == 50
    assert by_stratum["comparison/qa_comparison_de_v1"] == 30
    ids = {c.id for c in chosen}
    assert {c.id for c in cases if c.category in PROBES} <= ids


def test_sampler_guarantees_thirty_per_category() -> None:
    chosen = sample_for_review(_full_pool(), seed=3)
    per_category = Counter(c.category for c in chosen if c.split is Split.FULL)
    for category in (Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON):
        assert per_category[category] >= 30
    assert per_category[Category.CROSS_LINGUAL] == 30  # 20 % would be 20: topped up
    assert per_category[Category.UNANSWERABLE] == 30


def test_sampler_takes_every_core_and_smoke_case() -> None:
    cases = _full_pool()
    ids = {c.id for c in sample_for_review(cases, seed=3)}
    assert {c.id for c in cases if c.split in {Split.CORE, Split.SMOKE}} <= ids


def test_sampler_is_deterministic_and_seed_dependent() -> None:
    cases = _full_pool()
    first = [c.id for c in sample_for_review(cases, seed=3)]
    assert first == [c.id for c in sample_for_review(cases, seed=3)]
    assert first != [c.id for c in sample_for_review(cases, seed=4)]


def test_eight_fixes_and_four_rejects_make_a_stratum_to_regenerate() -> None:
    cases = build_cases(Split.FULL, {(Category.FACTUAL, "qa_factual_de_v1"): 100})
    items = (
        [item(c, "fix", fixed_question=f"{c.question} Bitte genau.") for c in cases[:8]]
        + [item(c, "reject") for c in cases[8:12]]
        + [item(c, "ok") for c in cases[12:]]
    )
    result = apply_decisions(
        cases, items, reviewer="model:ollama/gemma3:12b@review_item_de_v1", today=REVIEW_DAY
    )
    (round_,) = result.rounds
    assert (round_.sampled, round_.bad, round_.error_rate) == (100, 12, 0.12)
    assert round_.round == 1
    assert round_.reviewer == "model:ollama/gemma3:12b@review_item_de_v1"
    assert round_.prompt_version == "qa_factual_de_v1"
    assert round_.date == date(2026, 11, 9)
    assert result.needs_regeneration == ("factual/qa_factual_de_v1",)
    assert error_rates(items)["factual/qa_factual_de_v1"].error_rate == 0.12


def test_a_stratum_at_ten_percent_is_not_regenerated() -> None:
    cases = build_cases(Split.FULL, {(Category.FACTUAL, "qa_factual_de_v1"): 100})
    items = [item(c, "reject" if n < 10 else "ok") for n, c in enumerate(cases)]
    rates = error_rates(items)
    assert rates["factual/qa_factual_de_v1"].needs_regeneration is False


def test_a_question_only_fix_replaces_the_question_and_marks_the_source() -> None:
    (case,) = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 1})
    fixed = "Wie lange ist die Kündigungsfrist in der Probezeit?"
    result = apply_decisions(
        [case], [item(case, "fix", fixed_question=fixed)], reviewer="model:x@p", today=REVIEW_DAY
    )
    (out,) = result.cases
    assert out.question == fixed
    assert out.source == "generated+model-reviewed"
    assert out.reference_answer == case.reference_answer


@pytest.mark.parametrize("split", [Split.CORE, Split.FULL])
def test_a_fix_with_a_rewritten_answer_becomes_a_reject(split: Split) -> None:
    cases = build_cases(split, {(Category.FACTUAL, "qa_factual_de_v1"): 2})
    rewrite = item(cases[0], "fix", fixed_question="Neue Frage?", fixed_answer="Neue Antwort.")
    result = apply_decisions(cases, [rewrite], reviewer="model:x@p", today=REVIEW_DAY)
    assert cases[0].id not in {c.id for c in result.cases}
    assert result.reasons[cases[0].id] == "reference_rewrite_forbidden"
    assert error_rates([rewrite])["factual/qa_factual_de_v1"].reject == 1


def test_a_reject_removes_the_whole_cluster_from_every_split() -> None:
    base = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 1})[0]
    mate = base.model_copy(update={"id": "mate", "base_id": "mate", "split": Split.FULL})
    variant = base.model_copy(
        update={"id": f"{base.id}~typos", "perturbation": "typos", "split": Split.ROBUST_PR}
    )
    other = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 2})[1]
    result = apply_decisions(
        [base, mate, variant, other], [item(base, "reject")], reviewer="model:x@p", today=REVIEW_DAY
    )
    assert [c.id for c in result.cases] == [other.id]
    assert set(result.rejected) == {base.id, "mate", variant.id}


def test_fixing_a_base_question_drops_its_stale_variants() -> None:
    base = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 1})[0]
    variant = base.model_copy(update={"id": f"{base.id}~typos", "perturbation": "typos"})
    result = apply_decisions(
        [base, variant],
        [item(base, "fix", fixed_question="Neue Frage?")],
        reviewer="r",
        today=REVIEW_DAY,
    )
    assert [c.id for c in result.cases] == [base.id]
    assert result.variants_dropped == (variant.id,)


def test_rounds_continue_the_numbering_of_the_manifest() -> None:
    cases = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 3})
    first = apply_decisions(cases, [item(c, "ok") for c in cases], reviewer="r", today=REVIEW_DAY)
    second = apply_decisions(
        first.cases,
        [item(c, "ok") for c in cases],
        reviewer="r",
        today=REVIEW_DAY,
        existing=first.rounds,
    )
    assert [r.round for r in (*first.rounds, *second.rounds)] == [1, 2]


def _smoke_pool() -> tuple[list[TestCase], list[ReviewItem]]:
    cases = build_cases(
        Split.FULL,
        {
            (Category.FACTUAL, "qa_factual_de_v1"): 40,
            (Category.MULTI_HOP, "qa_multi_hop_de_v1"): 20,
            (Category.COMPARISON, "qa_comparison_de_v1"): 12,
            (Category.UNANSWERABLE, None): 15,
            (Category.LEAK_PROBE, None): 4,
            (Category.INJECTION, None): 4,
            (Category.SYSTEM_PROMPT_EXTRACTION, None): 4,
        },
    )
    return cases, [item(c, "ok") for c in cases]


def test_select_smoke_meets_the_rule() -> None:
    cases, items = _smoke_pool()
    chosen = select_smoke(cases, items, seed=5)
    assert len(chosen) == 50
    per_category = Counter(c.category for c in chosen)
    assert all(n >= 3 for n in per_category.values())
    assert set(per_category) == {c.category for c in cases}
    assert sum(n for cat, n in per_category.items() if cat in PROBES) >= 5
    assert [c.id for c in chosen] == [c.id for c in select_smoke(cases, items, seed=5)]
    assert [c.id for c in chosen] != [c.id for c in select_smoke(cases, items, seed=6)]


def test_select_smoke_skips_items_that_are_not_clean_ok() -> None:
    cases, items = _smoke_pool()
    spoiled = {c.id for c in cases[:30]}
    flagged = [
        item(c, "ok", reasons=("citation_mismatch",))
        if c.id in spoiled and n % 2
        else item(c, "reject")
        if c.id in spoiled
        else it
        for n, (c, it) in enumerate(zip(cases, items, strict=True))
    ]
    chosen = select_smoke(cases, flagged, seed=5)
    assert not spoiled & {c.id for c in chosen}


def test_select_smoke_fails_when_a_category_is_too_small() -> None:
    cases, items = _smoke_pool()
    few = [c for c in cases if c.category is not Category.COMPARISON] + [
        c for c in cases if c.category is Category.COMPARISON
    ][:2]
    with pytest.raises(DatasetError, match="comparison"):
        select_smoke(few, [i for i in items if i.case_id in {c.id for c in few}], seed=5)


def _decision(case_id: str, *, ok: bool = True) -> SpotDecision:
    return SpotDecision(
        case_id=case_id,
        citation_ok=ok,
        plausible=True,
        reviewer="owner-spotcheck:anna",
        ts=datetime(2026, 11, 9, 12, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(("flagged", "trusted"), [(5, False), (4, True), (0, True)])
def test_spotcheck_trust_threshold_is_ten_percent_of_the_ok_items(
    flagged: int, *, trusted: bool
) -> None:
    cases = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 50})
    items = [item(c, "ok" if n < 40 else "fix", fixed_question="x?") for n, c in enumerate(cases)]
    decisions = [_decision(c.id, ok=n >= flagged) for n, c in enumerate(cases)]
    assert spotcheck_trust(decisions, items) is trusted


def test_spotcheck_trust_ignores_flags_on_items_the_model_already_fixed() -> None:
    cases = build_cases(Split.CORE, {(Category.FACTUAL, "qa_factual_de_v1"): 10})
    items = [item(c, "ok" if n < 8 else "fix", fixed_question="x?") for n, c in enumerate(cases)]
    decisions = [_decision(c.id, ok=n < 8) for n, c in enumerate(cases)]
    assert spotcheck_trust(decisions, items) is True


def test_spotcheck_sample_covers_all_smoke_and_is_seeded() -> None:
    smoke = build_cases(Split.SMOKE, {(Category.FACTUAL, "qa_factual_de_v1"): 30}, "smoke")
    core = build_cases(
        Split.CORE,
        {
            (Category.FACTUAL, "qa_factual_de_v1"): 60,
            (Category.MULTI_HOP, "qa_multi_hop_de_v1"): 20,
        },
        "core",
    )
    cases = smoke + core
    items = [
        item(c, "fix", fixed_question="x?") if n % 4 == 0 else item(c, "ok")
        for n, c in enumerate(cases)
    ]
    picked = sample_spotcheck(cases, items, seed=9, size=50)
    assert len(picked) == 50
    assert {c.id for c in smoke} <= {c.id for c in picked}
    drawn = [c for c in picked if c.split is Split.CORE]
    assert len(drawn) == 20
    assert {c.category for c in drawn} == {Category.FACTUAL, Category.MULTI_HOP}
    assert [c.id for c in picked] == [c.id for c in sample_spotcheck(cases, items, seed=9, size=50)]


def test_spotcheck_sample_keeps_all_smoke_even_above_the_size() -> None:
    smoke = build_cases(Split.SMOKE, {(Category.FACTUAL, "qa_factual_de_v1"): 12}, "smoke")
    picked = sample_spotcheck(smoke, [item(c, "ok") for c in smoke], seed=1, size=5)
    assert len(picked) == 12
