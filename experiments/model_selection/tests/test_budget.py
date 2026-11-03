"""T3.1b budget.py tests: lanes, reranker rule, nightly, judge context rule, fits()."""

from typing import Any

import pytest
from model_selection import budget as b
from model_selection import scenarios as sc

GEN = b.Lane(
    calls=300, prompt_tokens=3500, out_tokens=200, prefill_tps=1200, decode_tps=18, slots=4
)
JUDGE = b.Lane(
    calls=900, prompt_tokens=3000, out_tokens=150, prefill_tps=2000, decode_tps=35, slots=4
)


def test_lane_minutes_shows_prefill_plus_decode() -> None:
    # 300*3500/1200 = 875 s ; 300*200/(4*18) = 833.33 s ; sum 1708.33 s = 28.47 min
    assert b.lane_minutes(GEN) == pytest.approx((875.0 + 833.3333333) / 60, rel=1e-6)
    # 900*3000/2000 = 1350 s ; 900*150/(4*35) = 964.2857 s -> 38.57 min
    assert b.lane_minutes(JUDGE) == pytest.approx((1350.0 + 964.2857143) / 60, rel=1e-6)


def _inputs(**kw: Any) -> b.PrInputs:
    base: dict[str, Any] = {
        "smoke": 50,
        "core": 300,
        "robust": 440,
        "gen": GEN,
        "judge": JUDGE,
        "embed_s": 0.05,
        "rerank_s": 1.2,
        "rerank_concurrency": 1.0,
    }
    base.update(kw)
    return b.PrInputs(**base)


def test_pr_is_max_of_three_lanes_and_robust_pr_adds_no_generation() -> None:
    est = b.pr_estimate(_inputs(gen=b.Lane(**{**GEN.__dict__, "calls": 350}), judge=JUDGE))
    assert est.gpu0_min == pytest.approx(
        b.lane_minutes(b.Lane(**{**GEN.__dict__, "calls": 350})) + 790 * 0.05 / 60
    )
    assert est.gpu1_min == pytest.approx(b.lane_minutes(JUDGE))
    assert est.binding in {"gpu0", "gpu1", "cpu"}
    assert est.total_min == max(est.gpu0_min, est.gpu1_min, est.cpu_min)
    assert est.over_budget == (est.total_min > 90)
    assert est.generations == 350  # robust_pr contributes 0 generations
    assert est.judge_calls == 900


def test_reranker_lane_rule() -> None:
    ok = b.rerank_verdict(queries=790, seconds_per_query=1.2, concurrency=1.0)
    assert ok.minutes == pytest.approx(15.8, abs=0.01)
    assert ok.robust_pr_reranker == "on"
    bad = b.rerank_verdict(queries=790, seconds_per_query=2.0, concurrency=1.0)
    assert bad.minutes == pytest.approx(26.33, abs=0.01)
    assert bad.robust_pr_reranker == "off"
    assert b.pr_estimate(_inputs(rerank_s=2.0)).cpu_min == pytest.approx(790 * 2.0 / 60)


def test_judged_subset_counts_and_gpu0_bound_remedies() -> None:
    inp = _inputs()
    sub = b.pr_estimate(inp, judged_subset=True)
    assert sub.generations == 50 + 80 + 110  # smoke + non-answerable core + subset answerable
    assert sub.judge_calls == 450  # judge calls on the 150 subset cases only (3 per case)
    # GPU0 120 min, GPU1 60 min: remedies start with the max_tokens pin; subset ~82 min
    rem = b.remedies(
        b.Estimate(gpu0_min=120.0, gpu1_min=60.0, cpu_min=5.0, generations=350, judge_calls=900),
        budget_min=90.0,
    )
    assert rem.binding == "gpu0"
    assert rem.steps[0].startswith("pin generation.max_tokens + prompt budget")
    assert rem.subset_min == pytest.approx(120.0 * 240 / 350, abs=0.5)
    assert rem.subset_min == pytest.approx(82.0, abs=0.5)
    assert rem.fits_with_subset is True


def test_nightly_lanes_and_flag() -> None:
    gen = b.Lane(
        calls=600, prompt_tokens=3500, out_tokens=200, prefill_tps=1200, decode_tps=18, slots=4
    )
    judge = b.Lane(
        calls=1800, prompt_tokens=3000, out_tokens=150, prefill_tps=2000, decode_tps=35, slots=4
    )
    est = b.nightly_estimate(gen, judge)
    assert est.total_min == pytest.approx(max(b.lane_minutes(gen), b.lane_minutes(judge)))
    assert est.over_budget is False
    slow = b.Lane(
        calls=600, prompt_tokens=3500, out_tokens=800, prefill_tps=100, decode_tps=5, slots=4
    )
    assert b.nightly_estimate(slow, judge).over_budget is True  # > 480 min


def test_two_slots_double_decode_time() -> None:
    two = b.with_slots(JUDGE, 2)
    decode4 = 900 * 150 / (4 * 35)
    decode2 = 900 * 150 / (2 * 35)
    assert b.lane_minutes(two) - b.lane_minutes(JUDGE) == pytest.approx((decode2 - decode4) / 60)


def test_judge_context_rule() -> None:
    assert b.required_judge_ctx(8192) == 12288
    assert (
        b.judge_ctx_problems({"gemma": 12288}, gen_ctx=8192, allowance=2900, vram_failed=set())
        == []
    )
    assert (
        "gemma"
        in b.judge_ctx_problems({"gemma": 12288}, gen_ctx=8192, allowance=3200, vram_failed=set())[
            0
        ]
    )
    low = b.judge_ctx_problems({"gemma": 8192}, gen_ctx=8192, allowance=2000, vram_failed=set())
    assert low
    assert "gemma" in low[0]
    assert (
        b.judge_ctx_problems({"gemma": 8192}, gen_ctx=8192, allowance=2000, vram_failed={"gemma"})
        == []
    )


def test_fits_with_explicit_overhead() -> None:
    kv = 0.48 * 1024 * 1024
    assert b.fits(
        num_ctx=12288,
        slots=4,
        kv_bytes_per_token=kv,
        weights_gib=15.6,
        overhead_gib=2.5,
        card_gib=44.0,
    )
    assert not b.fits(
        num_ctx=16384,
        slots=4,
        kv_bytes_per_token=kv,
        weights_gib=15.6,
        overhead_gib=2.5,
        card_gib=44.0,
    )
    assert b.fits(
        num_ctx=16384,
        slots=2,
        kv_bytes_per_token=kv,
        weights_gib=15.6,
        overhead_gib=2.5,
        card_gib=44.0,
    )
    assert b.total_gib(12288, 4, kv, 15.6, 2.5) == pytest.approx(41.1, abs=0.05)


def test_measured_scenarios_apply_the_20_percent_margin_rule() -> None:
    """Above 72 min (20 % margin) does not fit: the subset is the PR default; 512 never fits."""
    assert pytest.approx(72.0) == sc.PR_LIMIT_MIN
    by_cap = {out: (full, sub) for out, full, sub in sc.scenarios()}
    assert by_cap[150][0].total_min <= sc.PR_LIMIT_MIN  # full core fits only at short answers
    assert by_cap[200][0].total_min > sc.PR_LIMIT_MIN  # 72.6 min: just over
    full256, sub256 = by_cap[256]
    assert full256.total_min > sc.PR_LIMIT_MIN  # 89.4 min: no margin at all
    assert sub256.total_min <= sc.PR_LIMIT_MIN  # 62.1 min: the subset keeps >= 30 % margin
    assert sc.margin_pct(sub256.total_min) > 25
    assert by_cap[512][1].total_min > sc.PR_LIMIT_MIN  # the 256 cap must stay
    gen1 = b.Lane(350, 1650, 256, 966.0, 19.4, slots=1)
    assert b.lane_minutes(b.with_slots(gen1, 4)) < b.lane_minutes(gen1) / 2  # why one slot is tight
    lines = sc.scenarios_report().splitlines()
    assert "does not fit" in lines[2]
    assert "subset fits" in lines[2]
