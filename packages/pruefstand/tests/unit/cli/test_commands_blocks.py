"""``run`` selection flags: block, counter file, stratum, splits (R12 N1.2, R13 P4.3 / P4.4)."""

import os
import time
from pathlib import Path

import pytest
from testsupport.cli_support import do_run, manifest_of
from typer.testing import CliRunner


def test_block_flag_is_written_to_run_json(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "2")
    manifest = manifest_of(result)
    assert manifest["block"] == 2
    assert manifest["n_cases"] == 4  # block 2 + two refusal cases


@pytest.mark.parametrize(
    ("counter", "expected"),
    [("4", 1), ("5", 2), ("3", 0), ("7", 1)],
)
def test_block_auto_reads_the_counter_file(  # noqa: PLR0917  (parametrized fixtures)
    cli: CliRunner,
    full_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counter: str,
    expected: int,
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text(counter + "\n", encoding="utf-8")
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == expected


def test_the_counter_variable_names_the_file_and_wins(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text("4", encoding="utf-8")
    other = tmp_path / "elsewhere" / "c"
    other.parent.mkdir()
    other.write_text("7", encoding="utf-8")
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(other))
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == 1
    other.write_text("5", encoding="utf-8")
    assert (
        manifest_of(
            do_run(cli, full_config, tmp_path / "r2", "--split", "full", "--block", "auto")
        )["block"]
        == 2
    )


def test_a_missing_counter_file_is_block_zero(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == 0


@pytest.mark.parametrize("content", ["abc", "-1", "", "1.5", "99999999999999999999999999"])
def test_an_unparsable_counter_is_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, content: str
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text(content, encoding="utf-8")
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2
    assert "nightly_counter" in result.output


def test_block_auto_does_not_depend_on_the_clock(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text("4", encoding="utf-8")
    blocks = []
    for index, stamp in enumerate(("2026-12-31T22:00:00+00:00", "2027-01-01T00:30:00+00:00")):
        frozen = time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
        monkeypatch.setattr(time, "time", lambda frozen=frozen: frozen)
        blocks.append(
            manifest_of(
                do_run(
                    cli, full_config, tmp_path / f"r{index}", "--split", "full", "--block", "auto"
                )
            )["block"]
        )
    assert blocks == [1, 1]


def test_stratum_refusal_is_recorded(cli: CliRunner, full_config: Path, tmp_path: Path) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--stratum", "refusal")
    )
    assert manifest["stratum"] == "refusal"
    assert manifest["n_cases"] == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--split", "full", "--stratum", "refusal", "--block", "1"],
        ["--split", "core", "--block", "1"],
        ["--split", "core", "--stratum", "blocks"],
        ["--split", "full", "--split", "core", "--block", "1"],
        ["--split", "smoke", "--judged-subset"],
        ["--split", "full", "--block", "7"],
        ["--split", "full", "--block", "sometimes"],
        ["--split", "nonsense"],
        ["--split", "rq1"],
    ],
)
def test_invalid_selection_flags_are_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, extra: list[str]
) -> None:
    assert do_run(cli, full_config, tmp_path / "r", *extra).exit_code == 2


def test_split_flags_override_the_configured_splits(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "smoke", "--split", "core")
    )
    assert manifest["splits"] == ["smoke", "core"] or set(manifest["splits"]) == {"smoke", "core"}
    assert manifest["n_cases"] == 4


def test_the_config_hash_sees_the_effective_splits(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    default = manifest_of(do_run(cli, full_config, tmp_path / "a"))
    overridden = manifest_of(do_run(cli, full_config, tmp_path / "b", "--split", "core"))
    assert default["config_hash"] != overridden["config_hash"]


def test_a_counter_that_is_a_fifo_is_exit_two_and_does_not_hang(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "counter"
    os.mkfifo(fifo)
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(fifo))
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2
    assert "nightly counter" in result.output


def test_a_counter_that_is_a_directory_is_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(tmp_path))
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2
