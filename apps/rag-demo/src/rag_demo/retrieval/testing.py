"""Test helper for T3.5, T3.7 and the mutation benchmark (T7.1a): is a request tenant-scoped?"""

from collections.abc import Mapping
from typing import NoReturn

from pydantic import ValidationError

from rag_demo.retrieval.filters import tenant_filter
from rag_demo.retrieval.query_builder import QdrantQuery


def _fail(message: str) -> NoReturn:
    raise AssertionError(message)


def assert_tenant_scoped(request: QdrantQuery | Mapping[str, object], tenant_id: str) -> None:
    """Assert that the request cannot return a chunk of a foreign tenant.

    Every prefetch leg and the top-level query must carry exactly ``tenant_filter(tenant_id)``
    (a ``must`` on ``tenant_id``), and there must be at least one leg. An unfiltered extra leg
    (M9), a ``should`` filter, or a missing filter (M8) fails.

    Args:
        request: The built ``QdrantQuery`` or its JSON body (as recorded from the wire).
        tenant_id: The calling tenant.

    Raises:
        AssertionError: The request is not scoped; the message names the offending part.
    """
    try:
        query = request if isinstance(request, QdrantQuery) else QdrantQuery.model_validate(request)
    except ValidationError:
        _fail("request is not a recognised Query API body with a must-filter")
    expected = tenant_filter(tenant_id)
    if not query.prefetch:
        _fail("request has no prefetch legs")
    for i, leg in enumerate(query.prefetch):
        if leg.filter != expected:
            _fail(f"prefetch[{i}] ({leg.using}) is not tenant-scoped")
    if query.filter != expected:
        _fail("top-level query is not tenant-scoped")
