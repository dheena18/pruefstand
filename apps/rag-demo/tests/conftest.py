"""Pytest configuration of rag-demo: Hypothesis profiles (D8-10) and shared paths."""

import os
from pathlib import Path

import pytest
from hypothesis import settings

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("nightly", max_examples=2000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

APP_DIR = Path(__file__).resolve().parents[1]
REPO = APP_DIR.parents[1]
CONFIGS = APP_DIR / "configs"
CASSETTES = Path(__file__).resolve().parent / "cassettes"
SLICE = REPO / "corpus" / "slice_v1"
_REQUEST_HEADERS = frozenset({"content-type", "accept"})


def _scrub_request(request):  # type: ignore[no-untyped-def]  # vcr hook, untyped upstream
    request.headers = {k: v for k, v in request.headers.items() if k.lower() in _REQUEST_HEADERS}
    return request


def _scrub_response(response):  # type: ignore[no-untyped-def]  # vcr hook, untyped upstream
    keep = {"content-type"}
    response["headers"] = {k: v for k, v in response["headers"].items() if k.lower() in keep}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    """Replay-only vcr with an allow-list of headers (no Authorization ever reaches a cassette)."""
    return {
        "match_on": ["method", "path"],
        "before_record_request": _scrub_request,
        "before_record_response": _scrub_response,
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    return str(CASSETTES)
