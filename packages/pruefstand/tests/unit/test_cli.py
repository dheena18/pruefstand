import re

from typer.testing import CliRunner

from pruefstand.cli import app

runner = CliRunner()


def test_help_lists_version_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pruefstand" in result.output
    assert "version" in result.output


def test_version_is_a_subcommand_and_prints_semver() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert re.match(r"^pruefstand \d+\.\d+\.\d+", result.output)
