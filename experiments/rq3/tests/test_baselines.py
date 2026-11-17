"""T7.2 S2: the naive mean gate and the no-slices gate on the gate's own test fixture."""

import numpy as np
import pytest
from rq3.baselines import naive_gate, no_slice_gate, overall_mean
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import DIRECTIONS, FAIL, PASS
from testsupport.gate_helpers import POLICY as GATE_POLICY

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunResults
from pruefstand.gate.policy import evaluate_gate

# the tenant slices of fixture F0 have 20 clusters each: below the shipped min_clusters 30
POLICY = GATE_POLICY.model_copy(update={"min_clusters": 10})


def runs(edit: dict[int, float], metric: str = "context_recall") -> tuple[RunResults, RunResults]:
    cases, values = fixture_f0()
    cand = {m: list(v) for m, v in values.items()}
    for i, value in edit.items():
        cand[metric][i] = value
    return make_run("base", cases, values), make_run("cand", cases, cand)


def three(edit: dict[int, float]) -> tuple[GateStatus, GateStatus, GateStatus]:
    base, cand = runs(edit)
    prod = evaluate_gate(base, cand, POLICY, np.random.default_rng(1), directions=DIRECTIONS)
    naive = naive_gate(prod, base, cand, POLICY, directions=DIRECTIONS)
    sliced = no_slice_gate(base, cand, POLICY, np.random.default_rng(1), directions=DIRECTIONS)
    return prod.status, naive, sliced.status


def test_identical_runs_pass_in_every_variant() -> None:
    assert three({}) == (PASS, PASS, PASS)


def test_a_drop_in_one_tenant_only_is_caught_by_the_slices_not_by_overall() -> None:
    base_value = fixture_f0()[1]["context_recall"][0]
    assert base_value is not None
    tenant_two = dict.fromkeys(range(80, 120), base_value - 0.12)  # 1/3 of the cases, overall -0.04
    prod, naive, sliced = three(tenant_two)
    assert prod is FAIL
    assert naive is PASS
    assert sliced is not FAIL


def test_a_large_drop_in_a_few_clusters_fails_the_naive_gate_only() -> None:
    base_value = fixture_f0()[1]["context_recall"][0]
    assert base_value is not None
    few = dict.fromkeys(
        range(10), 0.0
    )  # 5 of 60 clusters lose everything: overall mean drops 0.067
    base, cand = runs(few)
    m_base, m_cand = overall_mean(base, "context_recall"), overall_mean(cand, "context_recall")
    assert m_base is not None
    assert m_cand is not None
    assert m_base - m_cand > 0.05
    prod, naive, _ = three(few)
    assert naive is FAIL
    assert prod is not FAIL


def test_naive_gate_names_a_metric_without_direction() -> None:
    base, cand = runs({})
    prod = evaluate_gate(base, cand, POLICY, np.random.default_rng(1), directions=DIRECTIONS)
    partial = {m: v for m, v in DIRECTIONS.items() if m != "faithfulness"}
    with pytest.raises(ConfigError, match="faithfulness"):
        naive_gate(prod, base, cand, POLICY, directions=partial)
