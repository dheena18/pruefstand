"""T5.4: the pass rule (D146) on statistics from real label vectors, the refusal rule (D193),
dev/test separation (AI13-12) and the selection (ADR-0019)."""

import math
import warnings

import pytest
from rq2.pass_rule import (
    Outcome,
    SetEvidence,
    metric_outcome,
    pass_rule_items,
    refusal_outcome,
    selection_items,
)
from rq2.rq2_config import REPO, load_config, load_items
from rq2.selection import Candidate, select_gating, select_tier1

from pruefstand.judges.calibration import cohens_kappa, specificity

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
DISC = {"swap_first_number": 0.95, "negate": 0.95}


def _full_set(disagree_fn: int, disagree_fp: int) -> float:
    labels = [1] * 100 + [0] * 100
    preds = (
        [0] * disagree_fn
        + [1] * (100 - disagree_fn)
        + [1] * disagree_fp
        + [0] * (100 - disagree_fp)
    )
    return cohens_kappa(labels, preds)


def _hard(rejected: int, n: int) -> tuple[float, float]:
    tnr, low, _ = specificity([0] * n, [0] * rejected + [1] * (n - rejected))
    return tnr, low


def _evidence(kappa: float, hard: tuple[float, float]) -> dict[str, SetEvidence]:
    return {"correctness": SetEvidence(kappa, *hard)}


def test_kappa_and_specificity_and_discrimination_pass() -> None:
    kappa = _full_set(15, 15)
    assert kappa == pytest.approx(0.7)
    out = metric_outcome(_evidence(kappa, _hard(125, 150)), ["correctness"], DISC)
    assert out.passed


def test_specificity_below_080_fails() -> None:
    out = metric_outcome(_evidence(_full_set(15, 15), _hard(118, 150)), ["correctness"], DISC)
    assert out.status == "failed"


def test_wilson_low_below_070_fails_even_at_080() -> None:
    tnr, low = _hard(24, 30)
    assert tnr == pytest.approx(0.80)
    assert low == pytest.approx(0.627, abs=1e-3)
    out = metric_outcome(_evidence(_full_set(15, 15), (tnr, low)), ["correctness"], DISC)
    assert not out.passed


def test_kappa_055_fails() -> None:
    kappa = _full_set(22, 23)
    assert kappa == pytest.approx(0.55, abs=1e-3)
    assert (
        metric_outcome(_evidence(kappa, _hard(135, 150)), ["correctness"], DISC).status == "failed"
    )


def test_an_all_negative_subset_has_no_usable_kappa() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = cohens_kappa([0] * 150, [0] * 125 + [1] * 25)
    assert math.isnan(value) or value == 0.0


def test_a_missing_gating_set_is_pending_never_passed() -> None:
    out = metric_outcome(_evidence(0.8, _hard(140, 150)), ["correctness", "legal_hard"], DISC)
    assert out.status == "pending"
    assert not out.passed


def test_low_discrimination_fails() -> None:
    out = metric_outcome(_evidence(0.8, _hard(140, 150)), ["correctness"], {"negate": 0.85})
    assert out.status == "failed"


def test_refusal_judge_with_a_high_hedged_fpr_fails() -> None:
    # 100 items: 50 refusals, 50 answers of which 25 hedged; 4 errors -> accuracy 0.96,
    # 2 of the 25 hedged answers called refusals -> FPR 0.08
    labels = [1] * 50 + [0] * 50
    types = [None] * 50 + ["hedged_answer"] * 25 + [None] * 25
    preds = [1] * 48 + [0] * 2 + [1] * 2 + [0] * 48
    out = refusal_outcome(labels, preds, types, near_misses=50)
    assert not out.passed
    assert any("FPR" in r for r in out.reasons)


def test_pass_rule_refuses_dev_items_and_selection_refuses_test_items() -> None:
    items = load_items(CFG.set_named("refusal"), None)
    dev = [i for i in items if i.calib_split == "dev"]
    test = [i for i in items if i.calib_split == "test"]
    with pytest.raises(ValueError, match="test"):
        pass_rule_items(dev)
    with pytest.raises(ValueError, match="dev"):
        selection_items(test)
    assert pass_rule_items(test) == test


def _cand(judge: str, status: str, kappa: float, cost: float = 1.0) -> Candidate:
    return Candidate(judge, "a", {"faithfulness": Outcome(status)}, kappa, cost)  # type: ignore[arg-type]  # literal from test table


def test_no_candidate_passes_pins_the_best_kappa_judge_as_failed() -> None:
    sel = select_gating(
        [_cand("ollama/gemma3:12b", "failed", 0.5), _cand("ollama/x", "failed", 0.55)],
        "ollama/gemma3:12b",
    )
    assert sel.judge == "ollama/x"
    assert not sel.passed


def test_a_passing_primary_is_never_replaced() -> None:
    sel = select_gating(
        [_cand("ollama/gemma3:12b", "passed", 0.7, 9.0), _cand("ollama/y", "passed", 0.9, 1.0)],
        "ollama/gemma3:12b",
    )
    assert sel.judge == "ollama/gemma3:12b"
    assert sel.passed


def test_tier1_choice_prefers_a_non_datagen_family_on_ties() -> None:
    kappas = {
        "github/openai/gpt-4.1-mini": {"faithfulness_constructed": 0.7},
        "github/mistral-ai/m": {"faithfulness_constructed": 0.7},
    }
    families = {"github/openai/gpt-4.1-mini": "gpt", "github/mistral-ai/m": "mistral"}
    assert select_tier1(kappas, families, "gpt") == "github/mistral-ai/m"
    assert select_tier1({}, families, "gpt") is None


def test_a_clean_refusal_result_without_the_near_miss_set_is_pending_never_passed() -> None:
    labels = [1] * 50 + [0] * 50
    types = [None] * 50 + ["hedged_answer"] * 25 + [None] * 25
    perfect = refusal_outcome(labels, labels, types, near_misses=0)
    assert perfect.status == "pending"
    assert not perfect.passed
    assert refusal_outcome(labels, labels, types, near_misses=50).passed
