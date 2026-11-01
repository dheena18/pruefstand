"""vcr settings for the cassette tests: replay only, allow-list scrubbing (testsupport.vcr_scrub)."""

from pathlib import Path

import pytest
from testsupport.vcr_scrub import VCR_CONFIG

CASSETTES = Path(__file__).resolve().parents[2] / "cassettes" / "llm"


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    return dict(VCR_CONFIG)


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    return str(CASSETTES)
