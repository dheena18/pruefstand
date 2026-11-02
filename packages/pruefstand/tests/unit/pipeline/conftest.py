from collections.abc import Iterator

import pytest
import respx
from testsupport.pipeline_support import BASE


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PRUEFSTAND_JUDGE_MODE",
        "PRUEFSTAND_STACK",
        "PRUEFSTAND_GH_MODELS_TOKEN",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_EVENT_PATH",
        "GITHUB_REPOSITORY",
        "PRUEFSTAND_NIGHTLY_COUNTER",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock
