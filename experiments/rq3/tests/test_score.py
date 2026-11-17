"""T7.2 S4 (pure core): detection is FAIL only, should-detect denominator, no-op rates, tiers."""

import pytest
from mutations.schema import load_all
from rq3.score import Decision, Rate, SummaryRow, Variant, matches_expected, rate, summarise

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import ConfigError

SPECS = {s.id: s for s in load_all()}
F, W, P = GateStatus.FAIL, GateStatus.WARN, GateStatus.PASS
STATISTICAL = sorted(i for i, s in SPECS.items() if s.stratum == "statistical" and not s.is_noop)


def d(
    entry: str,
    status: GateStatus,
    *,
    variant: Variant = "pruefstand",
    tier: str = "pr",
    rep: int = 0,
) -> Decision:
    return Decision.model_validate(
        {"entry": entry, "rep": rep, "variant": variant, "tier": tier, "status": status}
    )


def cell(rows: list[SummaryRow], variant: str, tier: str, outcome: str) -> Rate:
    (hit,) = [r for r in rows if (r.variant, r.tier, r.outcome) == (variant, tier, outcome)]
    return hit.rate


def test_detection_counts_fail_only_and_warn_is_reported_apart() -> None:
    should = dict.fromkeys(STATISTICAL, True)
    rows = summarise([d("M01", F), d("M10", W), d("M13", P)], SPECS, should)
    det = cell(rows, "pruefstand", "pr", "detection_statistical")
    warn = cell(rows, "pruefstand", "pr", "warn_statistical")
    assert (det.k, det.n) == (1, 3)
    assert (warn.k, warn.n) == (1, 3)


def test_below_delta_mutations_leave_the_detection_denominator() -> None:
    should = dict.fromkeys(STATISTICAL, True) | {"M13": False}
    rows = summarise([d("M01", F), d("M13", F)], SPECS, should)
    assert cell(rows, "pruefstand", "pr", "detection_statistical").n == 1
    flagged = cell(rows, "pruefstand", "pr", "below_delta_flagged")
    assert (flagged.k, flagged.n) == (1, 1)


def test_noops_give_false_block_and_false_warn_with_wilson_intervals() -> None:
    noops = [d("N01", P, rep=r) for r in range(3)] + [d("N02", W), d("N03", F)]
    rows = summarise(noops, SPECS, {})
    block, warn = (
        cell(rows, "pruefstand", "pr", "false_block"),
        cell(rows, "pruefstand", "pr", "false_warn"),
    )
    assert (block.k, block.n, warn.k, warn.n) == (1, 5, 1, 5)
    assert 0 < block.ci_low < 0.2 < block.ci_high < 1


def test_strata_deterministic_and_normaliser_have_their_own_rows() -> None:
    rows = summarise(
        [d("M08", F), d("M16", F), d("M20", P), d("M20", F, tier="nightly")], SPECS, {}
    )
    assert cell(rows, "pruefstand", "pr", "detection_deterministic").k == 2
    assert cell(rows, "pruefstand", "pr", "normaliser_pass").k == 1
    assert cell(rows, "pruefstand", "nightly", "normaliser_pass").k == 0


def test_variants_and_tiers_are_counted_apart() -> None:
    should = dict.fromkeys(STATISTICAL, True)
    rows = summarise([d("M06", F, tier="nightly"), d("M01", F, variant="naive")], SPECS, should)
    assert cell(rows, "pruefstand", "nightly", "detection_statistical").k == 1
    assert cell(rows, "naive", "pr", "detection_statistical").k == 1


def test_wrong_tier_unknown_entry_and_missing_true_effect_are_refused() -> None:
    with pytest.raises(ConfigError, match=r"X3\.10"):
        summarise([d("M06", F, tier="pr")], SPECS, {"M06": True})
    with pytest.raises(ConfigError, match="not an entry"):
        summarise([d("M11", F)], SPECS, {})  # pending entries are never scored
    with pytest.raises(ConfigError, match="true-effect"):
        summarise([d("M01", F)], SPECS, {})


def test_expected_status_comparison() -> None:
    assert matches_expected(d("M08", F), SPECS["M08"])
    assert not matches_expected(d("N01", W), SPECS["N01"])
    assert rate(0, 0).rate is None
