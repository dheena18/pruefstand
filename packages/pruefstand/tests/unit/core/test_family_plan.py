from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from pruefstand.core.models_family import known_families

ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(scope="module")
def plan() -> dict[str, str]:
    text = files("pruefstand.core.data").joinpath("model_families.yaml").read_text("utf-8")
    parsed = yaml.safe_load(text)["plan"]
    assert isinstance(parsed, dict)
    return parsed


def test_plan_parses_with_exactly_the_roles(plan: dict[str, str]) -> None:
    assert set(plan) == {
        "generator",
        "judge_pr",
        "judge_nightly",
        "judge_tier1",
        "datagen",
        "datagen_private",
    }
    assert plan["generator"] == "qwen"


def test_one_judge_for_pr_and_nightly(plan: dict[str, str]) -> None:
    assert plan["judge_pr"] == plan["judge_nightly"] == "gemma"  # ADR-0019, D329
    assert "judge_pr_alt" not in plan


@pytest.mark.parametrize("role", ["judge_pr", "judge_nightly", "judge_tier1", "datagen"])
def test_roles_differ_from_generator(plan: dict[str, str], role: str) -> None:
    assert plan[role] != plan["generator"]


def test_datagen_private_is_the_local_judge_family(plan: dict[str, str]) -> None:
    assert plan["datagen_private"] != plan["generator"]
    assert plan["datagen_private"] == "gemma"  # D330: written locally by the judge model


def test_public_datagen_differs_from_the_judges(plan: dict[str, str]) -> None:
    assert plan["datagen"] not in {plan["judge_pr"], plan["judge_nightly"]}
    assert plan["datagen"] not in {"qwen", "gemma"}


def test_plan_families_are_known(plan: dict[str, str]) -> None:
    assert set(plan.values()) <= known_families()


def test_live_example_judge_is_the_tier1_family(plan: dict[str, str]) -> None:
    example = yaml.safe_load((ROOT / "examples/live/pruefstand.yaml").read_text("utf-8"))
    assert example["judge"]["pr"]["family"] == plan["judge_tier1"]
