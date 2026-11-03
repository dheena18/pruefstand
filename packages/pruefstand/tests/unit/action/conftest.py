from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from testsupport.pipeline_support import BUG_URL, GOOD_URL
from testsupport.target_cassette import TargetCassette


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
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
        "PRUEFSTAND_LOG_JSON",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path / "home"))


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        TargetCassette("good").install(mock, GOOD_URL)
        TargetCassette("bug_tenant").install(mock, BUG_URL)
        yield mock
