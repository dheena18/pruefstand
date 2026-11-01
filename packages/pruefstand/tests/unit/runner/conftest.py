from collections.abc import AsyncIterator, Iterator

import pytest
import respx
from testsupport.runner_support import BASE, new_adapter

from pruefstand.adapters.http import HttpTargetAdapter


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = new_adapter()
    yield instance
    await instance.aclose()
