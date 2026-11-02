from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from testsupport.pipeline_support import GOOD_URL
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner


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
