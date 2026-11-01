"""Pytest configuration of rag-demo: Hypothesis profiles (D8-10) and shared paths."""

import os
from typing import Any

import pytest
from hypothesis import settings
from rd_support import CASSETTES

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("nightly", max_examples=2000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

_REQUEST_HEADERS = frozenset({"content-type", "accept"})


def _scrub_request(request: Any) -> Any:
    request.headers = {k: v for k, v in request.headers.items() if k.lower() in _REQUEST_HEADERS}
    return request


def _scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    keep = {"content-type"}
    response["headers"] = {k: v for k, v in response["headers"].items() if k.lower() in keep}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    """Replay-only vcr with an allow-list of headers (no Authorization ever reaches a cassette)."""
    return {
        "match_on": ["method", "path", "body"],
        "before_record_request": _scrub_request,
        "before_record_response": _scrub_response,
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    return str(CASSETTES)
