"""Fixtures of the orchestrator tests."""

import pytest
from orch_testkit import SpyPoster


@pytest.fixture
def poster() -> SpyPoster:
    return SpyPoster()
