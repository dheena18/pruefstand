"""T1.13c: a target's own generator timeout is not transient, other 5xx stay transient (D624).

Pairs with ``apps/rag-demo/tests/unit/test_api_generation.py``, which pins the body below.
"""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
import respx

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

BASE = "http://target.test"
REQ = TargetRequest(tenant_id=TenantId("public"), question="Frage", top_k=None, request_id="c-1")
GENERATOR_TIMEOUT = {"detail": {"code": "generator_timeout", "message": "generator timed out"}}


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=2))
    yield instance
    await instance.aclose()


@pytest.mark.parametrize(
    ("status", "body", "transient"),
    [
        (504, json.dumps(GENERATOR_TIMEOUT), False),  # the target's own generator timeout
        (504, "upstream timed out", True),  # a proxy in front of the target
        (504, json.dumps({"detail": {"code": "other"}}), True),
        (504, json.dumps({"detail": "generator_timeout"}), True),  # wrong shape
        (503, json.dumps(GENERATOR_TIMEOUT), True),  # the code only counts on 504
        (500, "boom", True),
    ],
)
async def test_only_the_generator_timeout_504_is_not_transient(
    router: respx.MockRouter,
    adapter: HttpTargetAdapter,
    status: int,
    body: str,
    transient: bool,  # noqa: FBT001
) -> None:
    router.post("/v1/query").respond(status, text=body)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is transient
