"""``pruefstand power`` (T1.10 S7, D56): power and minimum detectable effect from ``gate.stats``."""

import re

import pytest
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.gate.stats import minimum_detectable_effect, power_estimate

runner = CliRunner()


def test_the_documented_example() -> None:
    result = runner.invoke(app, ["power", "--sigma", "0.25", "--n", "300", "--delta", "0.03"])
    assert result.exit_code == 0
    assert re.fullmatch(r"power=0\.9\d+ mde=0\.04\d*\n", result.stdout)


def test_options_reach_gate_stats() -> None:
    args = [
        "power",
        "--sigma",
        "0.3",
        "--n",
        "120",
        "--delta",
        "0.05",
        "--alpha",
        "0.05",
        "--m",
        "4",
    ]
    result = runner.invoke(app, [*args, "--true-drop", "0.08"])
    power = power_estimate(0.3, 120, 0.05, 0.05, 4, true_drop=0.08)
    mde = minimum_detectable_effect(0.3 / 120**0.5, 0.05, 0.05, m=4)
    assert result.stdout.strip() == f"power={power:.3f} mde={mde:.4f}"


@pytest.mark.parametrize(
    "bad",
    [
        ["--n", "0"],
        ["--n", "-3"],
        ["--sigma", "0"],
        ["--sigma", "nan"],
        ["--delta", "-0.1"],
        ["--alpha", "1.5"],
        ["--m", "0"],
    ],
)
def test_invalid_numbers_are_a_usage_error(bad: list[str]) -> None:
    base = {"--sigma": "0.25", "--n": "300", "--delta": "0.03"}
    for flag, value in zip(bad[::2], bad[1::2], strict=True):
        base[flag] = value
    args = [part for pair in base.items() for part in pair]
    result = runner.invoke(app, ["power", *args])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Traceback" not in result.output


def test_an_absurdly_large_n_is_a_usage_error() -> None:
    args = ["power", "--sigma", "0.25", "--n", "1" + "0" * 400, "--delta", "0.03"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Traceback" not in result.output
