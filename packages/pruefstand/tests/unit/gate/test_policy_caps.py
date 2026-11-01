"""Judge-error and baseline-error caps through ``evaluate_gate`` (review of PR #22, rounds 2-4)."""

import numpy as np
import pytest
from testsupport.builders import fixture_f0, make_case, make_run
from testsupport.gate_helpers import DIRECTIONS, FAIL, PASS, POLICY, row

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.gate.policy import evaluate_gate


def _evaluate(base: RunResults, cand: RunResults) -> GateReport:
    return evaluate_gate(base, cand, POLICY, np.random.default_rng(1), directions=DIRECTIONS)


HARD = {"canary_leak": 0.0, "tenant_leak": 0.0, "system_prompt_leak": 0.0}


def _custom(  # noqa: PLR0913  (test helper)
    n_clusters: int,
    per_cluster: int,
    cand_edit: dict[int, float | None],
    *,
    metric: str = "faithfulness",
    cand_value: float = 0.9,
    en_clusters: int = 0,
    en_last: int = 0,
    base_edit: dict[int, float | None] | None = None,
    small_tenant: int = 0,
    policy: GatePolicy = POLICY,
) -> GateReport:
    n = n_clusters * per_cluster
    cases = [
        make_case(
            i,
            cluster=i // per_cluster,
            tenant="klein" if i >= n - small_tenant else "kanzlei_mueller",
            lang="en"
            if i // per_cluster < en_clusters or i // per_cluster >= n_clusters - en_last
            else "de",
        )
        for i in range(n)
    ]
    others = {"context_recall": 0.8, "citation_recall": 0.7, "language_match": 1.0}
    base: dict[str, list[float | None]] = {
        m: [v] * n for m, v in {**others, "faithfulness": 0.9, "error_rate": 0.0, **HARD}.items()
    }
    base["injection_success"] = [0.0] * n
    for i, v in (base_edit or {}).items():
        base[metric][i] = v
    cand = {k: list(v) for k, v in base.items()}
    cand[metric] = [cand_value] * n
    for i, v in cand_edit.items():
        cand[metric][i] = v
    return evaluate_gate(
        make_run("base", cases, base),
        make_run("cand", cases, cand),
        policy,
        np.random.default_rng(1),
        directions=DIRECTIONS,
    )


def test_m1_a_slice_that_loses_its_cases_to_judge_errors_cannot_vanish() -> None:
    """300 one-case clusters, 60 of them lang=en: all 60 judge-errored, the rest unchanged."""
    report = _custom(300, 1, dict.fromkeys(range(60), None), en_clusters=60)
    en = row(report.decisions, "faithfulness", "lang", "en")
    assert en.status is FAIL
    assert report.status is FAIL
    control = _custom(300, 1, dict.fromkeys(range(60), 0.0), en_clusters=60)
    assert row(control.decisions, "faithfulness", "lang", "en").status is FAIL


def test_m1_exclusion_cannot_push_overall_below_the_cluster_minimum() -> None:
    """35 clusters of 3; 7 whole clusters judge-errored (20 %); faithfulness 0.4 vs 0.9."""
    report = _custom(35, 3, dict.fromkeys(range(21), None), cand_value=0.4)
    overall = row(report.decisions, "faithfulness", "overall")
    assert overall.informational_reason is None
    assert overall.status is FAIL
    assert report.status is FAIL


def test_m1_small_exclusions_stay_excluded_per_slice() -> None:
    report = _custom(300, 1, dict.fromkeys(range(5), None), en_clusters=60)
    assert row(report.decisions, "faithfulness", "lang", "en").status is PASS
    assert report.n_excluded == {"faithfulness": 5}


def test_empty_baseline_is_an_input_error() -> None:
    empty = make_run("base", [], {m: [] for m in DIRECTIONS})
    cases, values = fixture_f0()
    with pytest.raises(GateInputError, match="no cases"):
        _evaluate(empty, make_run("cand", cases, values))


def test_metric_without_usable_baseline_values_is_an_input_error() -> None:
    cases, values = fixture_f0()
    values = {**values, "faithfulness": [float("nan")] * 120}
    with pytest.raises(GateInputError, match="faithfulness"):
        _evaluate(make_run("base", cases, values), make_run("cand", cases, fixture_f0()[1]))


def test_duplicated_case_ids_are_an_input_error() -> None:
    policy = GatePolicy(metrics={"error_rate": MetricPolicy(max_value=0.02)}, n_resamples=2000)
    cases = [make_case(i, cluster=i) for i in range(10)]
    base = make_run("base", cases, {**{m: [0.0] * 10 for m in HARD}, "error_rate": [0.0] * 10})
    erring = [1.0] + [0.0] * 9
    bad_cases = cases * 10
    cand = make_run(
        "cand", bad_cases, {**{m: [0.0] * 100 for m in HARD}, "error_rate": erring + [0.0] * 90}
    )
    with pytest.raises(GateInputError, match="duplicate"):
        evaluate_gate(base, cand, policy, np.random.default_rng(1), directions=DIRECTIONS)


def test_m1_errors_hiding_a_small_untestable_slice_are_filled_everywhere() -> None:
    """The last 29 of 300 one-case clusters are lang=en (< min_clusters), all judge-errored."""
    errors = dict.fromkeys(range(271, 300), None)
    report = _custom(300, 1, errors, en_last=29)
    assert report.status is FAIL
    assert row(report.decisions, "faithfulness", "overall").status is FAIL
    control = _custom(300, 1, dict.fromkeys(range(271, 300), 0.0), en_last=29)
    assert control.status is FAIL


def test_m2_baseline_errors_on_a_whole_slice_are_an_input_error() -> None:
    en = range(60)
    with pytest.raises(GateInputError, match="baseline"):
        _custom(300, 1, dict.fromkeys(en, 0.0), en_clusters=60, base_edit=dict.fromkeys(en, None))


def test_m2_a_slice_without_baseline_values_is_still_listed() -> None:
    en = range(60)
    report = _custom(
        300, 1, dict.fromkeys(en, 0.0), en_clusters=60, base_edit=dict.fromkeys(en, float("nan"))
    )
    listed = row(report.decisions, "faithfulness", "lang", "en")
    assert listed.status is GateStatus.INSUFFICIENT_DATA


def test_baseline_error_in_a_tiny_slice_does_not_raise() -> None:
    """A 4-case tenant is never testable; one baseline error (25 %) must not raise."""
    report = _custom(300, 1, {}, small_tenant=4, base_edit={299: None})
    assert row(report.decisions, "faithfulness", "tenant", "klein").status is (
        GateStatus.INSUFFICIENT_DATA
    )


def test_baseline_errors_above_the_cap_on_a_testable_slice_raise() -> None:
    en = range(60)
    with pytest.raises(GateInputError, match="baseline"):
        _custom(300, 1, {}, en_clusters=60, base_edit=dict.fromkeys(range(18), None))
    _custom(300, 1, {}, en_clusters=60, base_edit=dict.fromkeys(range(12), None))
    assert len(en) == 60


def test_quarter_of_the_cases_judge_errored_everywhere_fails_closed() -> None:
    errors = dict.fromkeys(range(0, 300, 4), None)
    assert _custom(300, 1, errors, en_clusters=60).status is FAIL


def test_overall_alone_gated_still_applies_the_cap() -> None:
    policy = POLICY.model_copy(update={"gated_slices": ("overall",)})
    errors = dict.fromkeys(range(0, 300, 4), None)
    assert _custom(300, 1, errors, en_clusters=60, policy=policy).status is FAIL
