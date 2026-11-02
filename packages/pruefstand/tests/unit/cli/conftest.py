from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from testsupport.cli_support import do_run, gate, run_dir
from testsupport.pipeline_support import (
    GOOD_URL,
    case_rows,
    config_file,
    mini_config,
    synthetic_config,
    write_dataset,
)
from testsupport.run_builders import make_case
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner

from pruefstand.core.enums import Split
from pruefstand.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "PRUEFSTAND_JUDGE_MODE",
        "PRUEFSTAND_STACK",
        "PRUEFSTAND_GH_MODELS_TOKEN",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_EVENT_PATH",
        "GITHUB_REPOSITORY",
        "GITHUB_TOKEN",
        "PRUEFSTAND_NIGHTLY_COUNTER",
        "PRUEFSTAND_LOG_JSON",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path / "home"))


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """The CLI points the log handler at the runner's temporary stderr; re-point it afterwards."""
    yield
    configure_logging()


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def good(router: respx.MockRouter) -> TargetCassette:
    cassette = TargetCassette("good")
    cassette.install(router, GOOD_URL)
    return cassette


@pytest.fixture
def good_config(tmp_path: Path) -> Path:
    return config_file(tmp_path / "good.yaml", mini_config())


@pytest.fixture
def gated_pair(cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path) -> Path:
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    assert gate(cli, good_config, two, one).exit_code == 0
    return two


@pytest.fixture
def full_config(tmp_path: Path, router: respx.MockRouter) -> Path:
    base = "http://target.test"
    router.get(f"{base}/v1/info").respond(404)
    router.post(f"{base}/v1/query").respond(
        200, json={"answer": "Antwort", "citations": [], "chunks": [], "refused": False}
    )
    rows = []
    for block in range(3):
        rows += case_rows([make_case(10 * block + j, split="full", block=block) for j in range(2)])
    rows += case_rows(
        [
            make_case(
                100 + j,
                split="full",
                category="unanswerable",
                expect_refusal=True,
                gold_doc_ids=[],
                gold_citations=[],
                reference_answer=None,
            )
            for j in range(2)
        ]
    )
    core = case_rows([make_case(200 + j, split="core") for j in range(2)])
    smoke = case_rows([make_case(300 + j, split="smoke") for j in range(2)])
    dataset = write_dataset(tmp_path / "ds", {"full": rows, "core": core, "smoke": smoke})
    return config_file(tmp_path / "full.yaml", synthetic_config(dataset, (Split.FULL,)))
