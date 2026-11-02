"""Reusable Target API v1 contract checker (T1.3 S4).

Used by T1.3 (HttpTargetAdapter against recorded example responses), T1.13 (the real
rag-demo, live) and T10.3 (framework adapters). The OpenAPI file is the single source of
truth for the wire shape.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator

from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import (
    RetrieveResponse,
    TargetInfo,
    TargetRequest,
    TargetResponse,
)
from pruefstand.core.protocols import TargetAdapter

CONTRACT_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = CONTRACT_DIR / "examples"
# Hand-written copies of the OpenAPI examples (examples/ holds rag-demo recordings since T1.13).
OPENAPI_EXAMPLES_DIR = CONTRACT_DIR / "examples_openapi"
OPENAPI_PATH = CONTRACT_DIR.parents[3] / "schemas" / "target-api-v1.openapi.yaml"


def load_example(name: str) -> Any:
    """Return the parsed JSON body of examples/<name>."""
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def load_openapi() -> dict[str, Any]:
    """Return the parsed target OpenAPI document."""
    loaded = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def schema_validator(component: str) -> Draft202012Validator:
    """Return a validator for #/components/schemas/<component> of the OpenAPI file.

    Raises:
        KeyError: The component does not exist.
    """
    spec = load_openapi()
    spec["components"]["schemas"][component]  # fail early with KeyError
    return Draft202012Validator(
        {"$ref": f"#/components/schemas/{component}", "components": spec["components"]}
    )


def assert_valid(component: str, body: object) -> None:
    """Assert that body validates against the OpenAPI component component."""
    errors = sorted(schema_validator(component).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, f"{component}: {errors[0].message} at {list(errors[0].path)}"


def _assert_ranks(chunks: Sequence[Any] | None) -> None:
    if chunks is None:
        return
    ranks = [chunk.rank for chunk in chunks]
    assert ranks == list(range(1, len(chunks) + 1)), f"chunk ranks not 1..n: {ranks}"


async def check_adapter_contract(
    adapter: TargetAdapter, questions: Sequence[tuple[str, str]]
) -> None:
    """Check that adapter honours Target API v1.

    Checks: info() is a TargetInfo or None; query() returns a TargetResponse
    that serialises to the OpenAPI QueryResponse; chunk ranks are 1..n without gaps;
    retrieve() is None or a valid RetrieveResponse; aclose() is idempotent.
    Every request carries a fresh random request_id (never a case id); that the adapter
    keeps it off the wire is asserted in test_http.py.

    Args:
        adapter: The adapter under test (closed by this function).
        questions: (tenant_id, question) pairs.

    Raises:
        AssertionError: A contract rule is violated.
    """
    info = await adapter.info()
    assert info is None or isinstance(info, TargetInfo)
    for tenant, question in questions:
        request = TargetRequest(
            tenant_id=TenantId(tenant), question=question, top_k=None, request_id=uuid4().hex
        )
        response = await adapter.query(request)
        assert isinstance(response, TargetResponse)
        assert_valid("QueryResponse", response.model_dump(mode="json"))
        _assert_ranks(response.chunks)
        retrieved = await adapter.retrieve(request)
        if retrieved is not None:
            assert isinstance(retrieved, RetrieveResponse)
            assert_valid("RetrieveResponse", retrieved.model_dump(mode="json"))
            _assert_ranks(retrieved.chunks)
    await adapter.aclose()
    await adapter.aclose()


def load_openapi_example(name: str) -> Any:
    """Load a hand-written example that equals the OpenAPI example (null and empty-chunk cases)."""
    return json.loads((OPENAPI_EXAMPLES_DIR / name).read_text(encoding="utf-8"))
