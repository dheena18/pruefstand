"""T6.3 S4, offline part: judge plan, scenario configs, MDE pre-check and the cause check."""

from pathlib import Path

import pytest
from noise.cause_switches import (
    BY_NAME,
    CONFIG_DIR,
    REPO,
    SCENARIOS,
    Scenario,
    ScenarioUnderpoweredError,
    decide,
    main,
    plan,
    precheck,
    problems,
    select,
    write_configs,
)
from testsupport.builders import fixture_f0, make_run

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunResults

DETERMINISTIC = ["retrieval", "citation_format", "language", "errors"]


def scenario_cfg(name: str) -> PruefstandConfig:
    return load_config(CONFIG_DIR / f"scenario_{name}.yaml")


@pytest.mark.parametrize("name", DETERMINISTIC)
def test_deterministic_scenarios_skip_the_judge_on_core(name: str) -> None:
    for run in plan(BY_NAME[name], Path("runs")):
        assert run.env == {"PRUEFSTAND_JUDGE_MODE": "skipped"}
        assert run.argv[-2:] == ("--split", "core")


def test_the_refusal_scenario_runs_a_fresh_judged_pair_on_the_refusal_stratum() -> None:
    baseline, switch = plan(BY_NAME["refusal_policy"], Path("runs"))
    for run in (baseline, switch):
        assert run.env == {}
        assert run.argv[-4:] == ("--split", "full", "--stratum", "refusal")
        assert "--block" not in run.argv
        assert "--from-store" not in run.argv
    assert baseline.argv[:2] == ("pruefstand", "run")  # a fresh run, never a stored baseline
    assert baseline.rag_config == "apps/rag-demo/configs/rag.gpu.yaml"
    assert switch.rag_config == "apps/rag-demo/configs/cause/no_refusal.yaml"


def test_every_switch_is_a_committed_cause_config() -> None:
    for scenario in SCENARIOS:
        _, switch = plan(scenario, Path("runs"))
        assert (REPO / switch.rag_config).is_file()


def test_committed_scenario_configs_are_the_generated_ones(tmp_path: Path) -> None:
    for path in write_configs(tmp_path):
        committed = CONFIG_DIR / path.name
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_each_scenario_gates_only_its_metric_on_overall(scenario: Scenario) -> None:
    cfg = scenario_cfg(scenario.name)
    assert list(cfg.gate.metrics) == [scenario.metric]
    assert cfg.gate.gated_slices == ("overall",)
    assert cfg.gate.min_clusters >= 30
    assert cfg.gate.hard_fail == load_config(REPO / "pruefstand.yaml").gate.hard_fail


def spread_run(run_id: str, metric: str, low: float, high: float) -> RunResults:
    cases, values = fixture_f0()
    values[metric] = [low if case.cluster_id < "k030" else high for case in cases]
    return make_run(run_id, cases, values)


def test_precheck_fails_an_underpowered_scenario_with_a_clear_message() -> None:
    cfg = scenario_cfg("retrieval")
    spread = spread_run("b", "context_recall", 0.0, 1.0)
    with pytest.raises(
        ScenarioUnderpoweredError, match=r"scenario underpowered: MDE 0\.\d+ > expected"
    ):
        precheck(spread, BY_NAME["retrieval"], cfg)
    flat = spread_run("b", "context_recall", 0.8, 0.8)
    assert precheck(flat, BY_NAME["retrieval"], cfg) == pytest.approx(0.05)  # the delta floor
    assert precheck(flat, BY_NAME["errors"], scenario_cfg("errors")) is None


@pytest.mark.parametrize(
    ("name", "metric", "value"),
    [
        ("retrieval", "context_recall", 0.3),
        ("citation_format", "citation_recall", 0.1),
        ("language", "language_match", 0.0),
        ("errors", "error_rate", 1.0),
    ],
)
def test_a_real_drop_of_the_target_metric_gives_the_expected_cause(
    name: str, metric: str, value: float
) -> None:
    cases, values = fixture_f0()
    baseline = make_run("base", cases, values)
    switch = make_run("switch", cases, {**values, metric: [value] * len(cases)})
    report = decide(baseline, switch, scenario_cfg(name))
    assert problems(BY_NAME[name], switch, report) == []


def test_problems_name_a_wrong_cause_and_an_infra_failure() -> None:
    cases, values = fixture_f0()
    baseline = make_run("base", cases, values)
    aborted = make_run("switch", cases, values, complete=False)
    manifest = aborted.manifest.model_copy(update={"infra_error": "tunnel_lost: reset"})
    switch = aborted.model_copy(update={"manifest": manifest})
    report = decide(baseline, make_run("same", cases, values), scenario_cfg("language"))
    found = problems(BY_NAME["language"], switch, report)
    assert any(p.startswith("infra_error") for p in found)
    assert any("incomplete" in p for p in found)
    assert any(p.startswith("likely_cause None") for p in found)


def test_select_and_the_cli() -> None:
    assert [s.name for s in select(["all"])] == [s.name for s in SCENARIOS]
    with pytest.raises(ConfigError, match="unknown scenarios"):
        select(["nope"])
    assert main(["--plan", "runs/noise/cause", "--scenarios", "language", "errors"]) == 0
    assert main(["--check", "a", "b", "--scenarios", "all"]) == 2
